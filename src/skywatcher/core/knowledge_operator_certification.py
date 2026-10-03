"""Operator-local certification for the cumulative implication sidecar.

The package reads the operator RLSM and MFL databases in read-only mode, evaluates
an independently reviewed 300-frame gold denominator, discovers a bounded
screenshot-to-MFL candidate union, validates explicit operator adjudications, and
materializes those reviewed decisions into a separate scratch sidecar database.

It never registers migration 0004, mutates the RLSM/MFL authorities, or changes
canonical flight-history rows.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ..fr24 import database_migrations
from .knowledge_implications import canonical_json

SCHEMA_VERSION = "skywatcher.operator-certification.v1"
REVIEW_SCHEMA_VERSION = "skywatcher.operator-binding-review.v1"
EXPECTED_GOLD_RECORDS = 300
REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEW_SCHEMA_PATH = (
    REPO_ROOT / "schemas" / "knowledge" / "operator_binding_review.v1.schema.json"
)

DISCOVERY_BASES = {
    "CALLSIGN_EXACT_CASEFOLD",
    "REGISTRATION_FOLDER_EXACT_CASEFOLD",
}
STRONG_POSITIVE_BASES = {
    "DISPLAYED_SOURCE_FLIGHT_ID",
    "NATIVE_TRACK_MATCH",
    "AUTHORITATIVE_SOURCE_LINK",
    "REVIEWED_TIME_ROUTE_CONTINUITY",
}
STRONG_NEGATIVE_BASES = {
    "NON_OVERLAPPING_TIME",
    "DIFFERENT_SOURCE_FLIGHT_ID",
    "CONTRADICTORY_TRACK",
    "AUTHORITATIVE_EXCLUSION",
}
WEAK_ONLY_BASES = {
    "CALLSIGN_ONLY",
    "REGISTRATION_ONLY",
    "SPATIAL_PROXIMITY",
    "NEAREST_TIME",
}
DECISIONS = {"UNREVIEWED", "SAME_EVENT", "DIFFERENT_EVENT", "UNRESOLVED"}


class OperatorCertificationError(RuntimeError):
    """Raised when an operator-corpus certification invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sqlite_logical_sha256(path: Path) -> str:
    """Hash a consistent SQLite logical snapshot without mutating the source."""
    if not path.is_file():
        raise OperatorCertificationError(f"database not found: {path}")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        with _open_readonly(path) as source:
            destination = sqlite3.connect(tmp_path)
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        return sha256_file(tmp_path)
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


def git_head(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OperatorCertificationError("cannot resolve git HEAD") from exc
    value = proc.stdout.strip()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise OperatorCertificationError("git HEAD is not a full lowercase SHA-1")
    return value


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise OperatorCertificationError(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _require_tables(conn: sqlite3.Connection, names: Iterable[str], label: str) -> None:
    present = _table_names(conn)
    missing = sorted(set(names) - present)
    if missing:
        raise OperatorCertificationError(
            f"{label} database missing required tables: {', '.join(missing)}"
        )


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise OperatorCertificationError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.casefold() == ".jsonl":
            rows = [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]
        else:
            value = json.loads(text)
            if not isinstance(value, list):
                raise OperatorCertificationError(
                    f"JSON file must contain an array: {path}"
                )
            rows = value
    except json.JSONDecodeError as exc:
        raise OperatorCertificationError(f"invalid JSON: {path}: {exc}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise OperatorCertificationError(f"all records must be objects: {path}")
    return list(rows)


def _resolve_gold_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
) -> sqlite3.Row:
    evidence_sets: list[set[int]] = []
    if row.get("screenshot_id") is not None:
        matches = conn.execute(
            "SELECT screenshot_id FROM screenshots WHERE screenshot_id=?",
            (row["screenshot_id"],),
        ).fetchall()
        evidence_sets.append({int(item[0]) for item in matches})
    if row.get("screenshot_sha256"):
        matches = conn.execute(
            "SELECT screenshot_id FROM screenshots WHERE lower(sha256)=lower(?)",
            (row["screenshot_sha256"],),
        ).fetchall()
        evidence_sets.append({int(item[0]) for item in matches})
    if row.get("filename"):
        matches = conn.execute(
            "SELECT screenshot_id FROM screenshots WHERE filename=?",
            (row["filename"],),
        ).fetchall()
        evidence_sets.append({int(item[0]) for item in matches})
    if not evidence_sets:
        raise OperatorCertificationError("gold row has no screenshot identity")
    resolved = set.intersection(*evidence_sets)
    if len(resolved) != 1:
        raise OperatorCertificationError(
            "gold screenshot identity is unresolved or contradictory"
        )
    screenshot_id = next(iter(resolved))
    result = conn.execute(
        """
        SELECT screenshot_id,sha256,filename,rel_path,ingest_status,ocr_status
        FROM screenshots
        WHERE screenshot_id=?
        """,
        (screenshot_id,),
    ).fetchone()
    if result is None:
        raise OperatorCertificationError("resolved gold screenshot disappeared")
    return result


def validate_gold_review(
    rlsm_db: Path,
    gold_path: Path,
    *,
    expected_records: int = EXPECTED_GOLD_RECORDS,
    corpus_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _load_records(gold_path)
    errors: list[dict[str, Any]] = []
    if len(rows) != expected_records:
        errors.append(
            {
                "kind": "gold_denominator",
                "expected": expected_records,
                "actual": len(rows),
            }
        )
    resolved_rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    source_bytes_verified = 0
    source_byte_failures = 0
    source_manifest_entries: list[dict[str, Any]] = []
    with _open_readonly(rlsm_db) as conn:
        _require_tables(conn, {"screenshots"}, "RLSM")
        for index, row in enumerate(rows):
            try:
                screenshot = _resolve_gold_row(conn, row)
            except OperatorCertificationError as exc:
                errors.append(
                    {
                        "kind": "gold_identity",
                        "index": index,
                        "error": str(exc),
                    }
                )
                continue
            sid = int(screenshot["screenshot_id"])
            if sid in seen:
                errors.append(
                    {
                        "kind": "gold_duplicate_resolved_screenshot",
                        "index": index,
                        "screenshot_id": sid,
                    }
                )
            seen.add(sid)
            annotator = str(row.get("annotator") or "").strip()
            reviewer = str(row.get("reviewed_by") or "").strip()
            if "labels" not in row:
                errors.append(
                    {
                        "kind": "gold_labels_not_explicit",
                        "index": index,
                        "screenshot_id": sid,
                    }
                )
            if not annotator or not reviewer or annotator.casefold() == reviewer.casefold():
                errors.append(
                    {
                        "kind": "gold_independent_review_missing",
                        "index": index,
                        "screenshot_id": sid,
                    }
                )
            source_sha = str(screenshot["sha256"]).lower()
            rel_path = str(screenshot["rel_path"])
            if corpus_root is not None:
                relative = Path(rel_path)
                canonical_prefix = Path("data") / "FR24_baseline"
                with contextlib.suppress(ValueError):
                    relative = relative.relative_to(canonical_prefix)
                source_path = corpus_root / relative
                if not source_path.is_file():
                    source_byte_failures += 1
                    errors.append(
                        {
                            "kind": "gold_source_missing",
                            "index": index,
                            "screenshot_id": sid,
                            "path": str(source_path),
                        }
                    )
                elif sha256_file(source_path).lower() != source_sha:
                    source_byte_failures += 1
                    errors.append(
                        {
                            "kind": "gold_source_sha256_mismatch",
                            "index": index,
                            "screenshot_id": sid,
                            "path": str(source_path),
                        }
                    )
                else:
                    source_bytes_verified += 1
                    source_manifest_entries.append(
                        {
                            "screenshot_id": sid,
                            "rel_path": rel_path,
                            "sha256": source_sha,
                        }
                    )
            resolved_rows.append(
                {
                    "screenshot_id": sid,
                    "sha256": source_sha,
                    "filename": str(screenshot["filename"]),
                    "rel_path": rel_path,
                    "gold_annotator": annotator,
                }
            )
    metrics = {
        "records": len(rows),
        "expected_records": expected_records,
        "unique_resolved_records": len(seen),
        "source_bytes_verified": source_bytes_verified,
        "source_byte_failures": source_byte_failures,
        "source_manifest_sha256": (
            sha256_canonical(sorted(source_manifest_entries, key=lambda item: item["screenshot_id"]))
            if corpus_root is not None and source_byte_failures == 0
            else None
        ),
        "error_count": len(errors),
        "status": "PASS" if not errors and len(rows) == expected_records else "FAIL",
    }
    return metrics, resolved_rows


def _discovery_norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.casefold() if text else None


def _mfl_indexes(
    conn: sqlite3.Connection,
) -> tuple[dict[str, list[sqlite3.Row]], dict[str, list[sqlite3.Row]]]:
    records = conn.execute(
        """
        SELECT corpus_record_id,corpus_uid,snapshot_id,source_flight_id_raw,
               callsign_raw,start_time_utc,end_time_utc
        FROM flight_corpus_records
        ORDER BY corpus_record_id
        """
    ).fetchall()
    callsigns: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_id = {int(row["corpus_record_id"]): row for row in records}
    for row in records:
        key = _discovery_norm(row["callsign_raw"])
        if key:
            callsigns[key].append(row)

    registrations: dict[str, dict[int, sqlite3.Row]] = defaultdict(dict)
    manifestations = conn.execute(
        """
        SELECT corpus_record_id,source_folder_raw
        FROM flight_source_manifestations
        WHERE source_folder_raw IS NOT NULL
        ORDER BY manifestation_id
        """
    ).fetchall()
    for item in manifestations:
        key = _discovery_norm(item["source_folder_raw"])
        record = by_id.get(int(item["corpus_record_id"]))
        if key and record is not None:
            registrations[key][int(record["corpus_record_id"])] = record
    return callsigns, {
        key: [bucket[rid] for rid in sorted(bucket)]
        for key, bucket in registrations.items()
    }


def _candidate_core(
    screenshot: Mapping[str, Any],
    aircraft: Mapping[str, Any],
    mfl: Mapping[str, Any],
    candidate_basis: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "screenshot": dict(screenshot),
        "aircraft_observation": dict(aircraft),
        "mfl_record": dict(mfl),
        "candidate_basis": sorted(candidate_basis),
        "candidate_state": "CANDIDATE_NOT_IDENTITY",
    }


def discover_binding_candidates(
    rlsm_db: Path,
    mfl_db: Path,
    gold_path: Path,
    *,
    expected_gold_records: int = EXPECTED_GOLD_RECORDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gold_metrics, gold_rows = validate_gold_review(
        rlsm_db,
        gold_path,
        expected_records=expected_gold_records,
    )
    if gold_metrics["status"] != "PASS":
        raise OperatorCertificationError(
            "gold review contract failed before candidate discovery"
        )

    candidates: list[dict[str, Any]] = []
    with _open_readonly(rlsm_db) as rlsm, _open_readonly(mfl_db) as mfl:
        _require_tables(rlsm, {"screenshots", "aircraft_observations"}, "RLSM")
        _require_tables(
            mfl,
            {
                "flight_corpus_records",
                "flight_source_manifestations",
                "flight_corpus_snapshots",
            },
            "MFL",
        )
        callsign_index, registration_index = _mfl_indexes(mfl)
        for screenshot in gold_rows:
            observations = rlsm.execute(
                """
                SELECT aircraft_obs_id,registration,callsign,identity_status,observed_at
                FROM aircraft_observations
                WHERE screenshot_id=?
                ORDER BY aircraft_obs_id
                """,
                (screenshot["screenshot_id"],),
            ).fetchall()
            for obs in observations:
                matches: dict[int, dict[str, Any]] = {}
                callsign = _discovery_norm(obs["callsign"])
                if callsign:
                    for record in callsign_index.get(callsign, []):
                        rid = int(record["corpus_record_id"])
                        matches.setdefault(rid, {"record": record, "basis": set()})
                        matches[rid]["basis"].add("CALLSIGN_EXACT_CASEFOLD")
                registration = _discovery_norm(obs["registration"])
                if registration:
                    for record in registration_index.get(registration, []):
                        rid = int(record["corpus_record_id"])
                        matches.setdefault(rid, {"record": record, "basis": set()})
                        matches[rid]["basis"].add(
                            "REGISTRATION_FOLDER_EXACT_CASEFOLD"
                        )
                for rid in sorted(matches):
                    record = matches[rid]["record"]
                    basis = sorted(matches[rid]["basis"])
                    aircraft = {
                        "aircraft_obs_id": int(obs["aircraft_obs_id"]),
                        "registration_raw": obs["registration"],
                        "callsign_raw": obs["callsign"],
                        "identity_status_raw": obs["identity_status"],
                        "observed_at": str(obs["observed_at"]),
                    }
                    mfl_record = {
                        "corpus_record_id": rid,
                        "corpus_uid": str(record["corpus_uid"]),
                        "snapshot_id": int(record["snapshot_id"]),
                        "source_flight_id_raw": record["source_flight_id_raw"],
                        "callsign_raw": record["callsign_raw"],
                        "start_time_utc": record["start_time_utc"],
                        "end_time_utc": record["end_time_utc"],
                    }
                    core = _candidate_core(screenshot, aircraft, mfl_record, basis)
                    candidate_id = sha256_canonical(core)
                    candidates.append(
                        {
                            **core,
                            "candidate_id": candidate_id,
                            "decision": "UNREVIEWED",
                            "decision_basis": [],
                            "independent_evidence_refs": [],
                            "reviewed_by": "",
                            "reviewed_at": "",
                            "notes": "",
                        }
                    )

    candidates.sort(key=lambda row: row["candidate_id"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "candidate_scope": "GOLD_300_EXACT_CALLSIGN_OR_REGISTRATION_DISCOVERY",
        "candidate_identity_rule": "DISCOVERY_ONLY_NOT_EVENT_IDENTITY",
        "gold_records": gold_metrics["records"],
        "gold_unique_resolved_records": gold_metrics["unique_resolved_records"],
        "candidate_count": len(candidates),
        "screenshots_with_candidates": len(
            {row["screenshot"]["screenshot_id"] for row in candidates}
        ),
        "candidate_manifest_sha256": sha256_canonical(
            [
                {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "decision",
                        "decision_basis",
                        "independent_evidence_refs",
                        "reviewed_by",
                        "reviewed_at",
                        "notes",
                    }
                }
                for row in candidates
            ]
        ),
    }
    return candidates, manifest


def write_review_template(
    candidates: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    template_path: Path,
    manifest_path: Path,
) -> None:
    template_path.parent.mkdir(parents=True, exist_ok=True)
    with template_path.open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(
                json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _validate_review_schema(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not REVIEW_SCHEMA_PATH.is_file():
        raise OperatorCertificationError(
            f"binding review schema not found: {REVIEW_SCHEMA_PATH}"
        )
    schema = json.loads(REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        for error in sorted(
            validator.iter_errors(dict(row)),
            key=lambda item: (tuple(str(part) for part in item.path), item.message),
        ):
            errors.append(
                {
                    "kind": "review_schema_error",
                    "index": index,
                    "path": "/".join(str(part) for part in error.path),
                    "error": error.message,
                }
            )
    return errors


def _review_core(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "candidate_id",
        "screenshot",
        "aircraft_observation",
        "mfl_record",
        "candidate_basis",
        "candidate_state",
    )
    return {key: row.get(key) for key in keys}


def validate_binding_review(
    review_path: Path,
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    review = _load_records(review_path)
    expected = {str(row["candidate_id"]): row for row in candidates}
    actual: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = _validate_review_schema(review)
    for index, row in enumerate(review):
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in actual:
            errors.append(
                {
                    "kind": "review_candidate_id_duplicate_or_missing",
                    "index": index,
                    "candidate_id": candidate_id,
                }
            )
            continue
        actual[candidate_id] = row

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        errors.append({"kind": "review_missing_candidates", "count": len(missing)})
    if extra:
        errors.append({"kind": "review_extra_candidates", "count": len(extra)})

    counts = defaultdict(int)
    for candidate_id in sorted(set(expected) & set(actual)):
        expected_row = expected[candidate_id]
        row = actual[candidate_id]
        if _review_core(row) != _review_core(expected_row):
            errors.append(
                {
                    "kind": "review_candidate_core_drift",
                    "candidate_id": candidate_id,
                }
            )
            continue
        decision = str(row.get("decision") or "")
        if decision not in DECISIONS:
            errors.append(
                {
                    "kind": "review_decision_invalid",
                    "candidate_id": candidate_id,
                    "decision": decision,
                }
            )
            continue
        counts[decision] += 1
        basis = set(row.get("decision_basis") or [])
        refs = row.get("independent_evidence_refs") or []
        reviewer = str(row.get("reviewed_by") or "").strip()
        reviewed_at = str(row.get("reviewed_at") or "").strip()
        gold_annotator = str(
            expected_row["screenshot"].get("gold_annotator") or ""
        ).strip()

        if decision == "UNREVIEWED":
            errors.append(
                {
                    "kind": "review_unreviewed_candidate",
                    "candidate_id": candidate_id,
                }
            )
            continue
        if not reviewer or not reviewed_at:
            errors.append(
                {
                    "kind": "review_receipt_incomplete",
                    "candidate_id": candidate_id,
                }
            )
        if reviewer and gold_annotator and reviewer.casefold() == gold_annotator.casefold():
            errors.append(
                {
                    "kind": "binding_review_not_independent_of_gold_annotator",
                    "candidate_id": candidate_id,
                }
            )
        if decision == "SAME_EVENT":
            if not basis.intersection(STRONG_POSITIVE_BASES) or not refs:
                errors.append(
                    {
                        "kind": "same_event_without_independent_strong_basis",
                        "candidate_id": candidate_id,
                    }
                )
        elif decision == "DIFFERENT_EVENT":
            if not basis.intersection(STRONG_NEGATIVE_BASES) or not refs:
                errors.append(
                    {
                        "kind": "different_event_without_independent_strong_basis",
                        "candidate_id": candidate_id,
                    }
                )
        elif decision == "UNRESOLVED" and basis.intersection(STRONG_POSITIVE_BASES):
            errors.append(
                {
                    "kind": "unresolved_contains_unadjudicated_positive_basis",
                    "candidate_id": candidate_id,
                }
            )
        allowed = STRONG_POSITIVE_BASES | STRONG_NEGATIVE_BASES | WEAK_ONLY_BASES
        if basis and not basis.issubset(allowed):
            errors.append(
                {
                    "kind": "review_basis_unknown",
                    "candidate_id": candidate_id,
                }
            )

    bounded_controls = counts["SAME_EVENT"] > 0 and counts["DIFFERENT_EVENT"] > 0
    if not candidates:
        errors.append({"kind": "candidate_denominator_empty"})
    status = "PASS"
    if errors:
        status = "FAIL"
    elif not bounded_controls or counts["UNRESOLVED"] > 0:
        status = "BLOCKED"
    metrics = {
        "candidate_count": len(candidates),
        "review_rows": len(review),
        "same_event": counts["SAME_EVENT"],
        "different_event": counts["DIFFERENT_EVENT"],
        "unresolved": counts["UNRESOLVED"],
        "unreviewed": counts["UNREVIEWED"],
        "positive_and_negative_controls_present": bounded_controls,
        "error_count": len(errors),
        "status": status,
    }
    return metrics, errors


def preflight(
    *,
    repo_root: Path,
    rlsm_db: Path,
    mfl_db: Path,
    corpus_root: Path,
    gold_path: Path,
    expected_git_sha: str | None = None,
) -> dict[str, Any]:
    head = git_head(repo_root)
    if expected_git_sha and head != expected_git_sha:
        raise OperatorCertificationError(
            f"git HEAD drift: expected {expected_git_sha}, found {head}"
        )
    if not corpus_root.is_dir():
        raise OperatorCertificationError(f"corpus root not found: {corpus_root}")
    gold_metrics, _ = validate_gold_review(
        rlsm_db,
        gold_path,
        corpus_root=corpus_root,
    )
    with _open_readonly(rlsm_db) as rlsm:
        _require_tables(
            rlsm,
            {"screenshots", "aircraft_observations", "source_manifestations"},
            "RLSM",
        )
    with _open_readonly(mfl_db) as mfl:
        _require_tables(
            mfl,
            {
                "flight_corpus_snapshots",
                "flight_corpus_records",
                "flight_source_manifestations",
            },
            "MFL",
        )
        mfl_records = int(
            mfl.execute("SELECT COUNT(*) FROM flight_corpus_records").fetchone()[0]
        )
    if any(migration.version == 4 for migration in database_migrations.MIGRATIONS):
        raise OperatorCertificationError(
            "migration 0004 is registered; operator certification requires it disabled"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if gold_metrics["status"] == "PASS" else "BLOCKED",
        "git_sha": head,
        "rlsm_db": str(rlsm_db),
        "rlsm_db_sha256": sha256_file(rlsm_db),
        "rlsm_db_logical_sha256": sqlite_logical_sha256(rlsm_db),
        "mfl_db": str(mfl_db),
        "mfl_db_sha256": sha256_file(mfl_db),
        "mfl_db_logical_sha256": sqlite_logical_sha256(mfl_db),
        "corpus_root": str(corpus_root),
        "gold_path": str(gold_path),
        "gold_sha256": sha256_file(gold_path),
        "gold_review": gold_metrics,
        "mfl_record_count": mfl_records,
        "migration_0004_registered": False,
        "canonical_mfl_mutation_authorized": False,
    }


def _artifact_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _apply_sidecar_schema(conn: sqlite3.Connection, schema_sql: str) -> None:
    database_migrations._begin_atomic_sql_script(conn, schema_sql)
    conn.commit()


def materialize_review_sidecar(
    *,
    sidecar_path: Path,
    schema_sql: str,
    reviewed_rows: Sequence[Mapping[str, Any]],
    rlsm_db_sha256: str,
    mfl_db_sha256: str,
    gold_sha256: str,
    review_sha256: str,
    git_sha: str,
    package_status: str,
) -> dict[str, Any]:
    manifest = {
        "git_sha": git_sha,
        "rlsm_db_sha256": rlsm_db_sha256,
        "mfl_db_sha256": mfl_db_sha256,
        "gold_sha256": gold_sha256,
        "review_sha256": review_sha256,
        "candidate_ids": sorted(str(row["candidate_id"]) for row in reviewed_rows),
    }
    input_sha = sha256_canonical(manifest)
    if sidecar_path.exists():
        existing = sqlite3.connect(f"file:{sidecar_path.resolve()}?mode=ro", uri=True)
        try:
            row = existing.execute(
                """
                SELECT input_manifest_sha256
                FROM swk_knowledge_run
                ORDER BY rowid
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise OperatorCertificationError(
                "existing scratch sidecar is unreadable; use a new output directory"
            ) from exc
        finally:
            existing.close()
        if row is None or str(row[0]) != input_sha:
            raise OperatorCertificationError(
                "scratch sidecar already exists for different inputs; "
                "use a new output directory"
            )
        return {
            "path": str(sidecar_path),
            "sha256": sha256_file(sidecar_path),
            "run_id": f"opcert-{input_sha[:20]}",
            "reused_identical_inputs": True,
            "canonical_event_count_claimed": False,
            "migration_0004_registered": False,
        }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sidecar_path)
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_sidecar_schema(conn, schema_sql)
    ruleset_sha = sha256_canonical(
        {
            "schema_version": SCHEMA_VERSION,
            "strong_positive": sorted(STRONG_POSITIVE_BASES),
            "strong_negative": sorted(STRONG_NEGATIVE_BASES),
            "discovery": sorted(DISCOVERY_BASES),
        }
    )
    run_id = f"opcert-{input_sha[:20]}"
    conn.execute(
        """
        INSERT INTO swk_knowledge_run(
          run_id,input_manifest_sha256,ruleset_sha256,baseline_commit,status,started_utc
        ) VALUES(?,?,?,?,?,?)
        """,
        (run_id, input_sha, ruleset_sha, git_sha, "VALIDATED", "operator-local"),
    )

    review_artifact = _artifact_id("review", review_sha256)
    conn.execute(
        """
        INSERT INTO swk_source_artifact(
          artifact_id,source_namespace,external_source_key_raw,source_snapshot_sha256,
          byte_sha256,source_kind,evidence_tier,visibility_class,provenance_status,
          availability,created_utc
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            review_artifact,
            "USER_UPLOAD",
            "operator-binding-review",
            review_sha256,
            review_sha256,
            "OPERATOR_BINDING_REVIEW",
            "UNKNOWN",
            "V2",
            "COMPLETE",
            "PRESENT",
            "operator-local",
        ),
    )
    conn.execute(
        """
        INSERT INTO swk_artifact_manifestation(
          manifestation_id,artifact_id,source_path_raw,source_record_key_raw,
          observed_utc,manifestation_metadata_json
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            _artifact_id("manifestation", review_artifact),
            review_artifact,
            "operator-binding-review.jsonl",
            review_sha256,
            "operator-local",
            "{}",
        ),
    )

    for row in reviewed_rows:
        candidate_id = str(row["candidate_id"])
        screenshot = row["screenshot"]
        mfl = row["mfl_record"]
        decision = str(row["decision"])
        shot_artifact = _artifact_id("rlsm", str(screenshot["sha256"]))
        mfl_artifact = _artifact_id(
            "mfl",
            f"{mfl['snapshot_id']}:{mfl['corpus_record_id']}:{mfl['corpus_uid']}",
        )
        for artifact_id, namespace, key, snapshot_sha, byte_sha, kind in (
            (
                shot_artifact,
                "RLSM_LOCAL",
                f"screenshot:{screenshot['screenshot_id']}",
                rlsm_db_sha256,
                str(screenshot["sha256"]),
                "SCREENSHOT",
            ),
            (
                mfl_artifact,
                "MFL_SNAPSHOT",
                f"record:{mfl['corpus_record_id']}:{mfl['corpus_uid']}",
                mfl_db_sha256,
                None,
                "MFL_RECORD",
            ),
        ):
            conn.execute(
                """
                INSERT OR IGNORE INTO swk_source_artifact(
                  artifact_id,source_namespace,external_source_key_raw,
                  source_snapshot_sha256,byte_sha256,source_kind,evidence_tier,
                  visibility_class,provenance_status,availability,created_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id,
                    namespace,
                    key,
                    snapshot_sha,
                    byte_sha,
                    kind,
                    "UNKNOWN",
                    "V2",
                    "COMPLETE",
                    "PRESENT",
                    "operator-local",
                ),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO swk_artifact_manifestation(
              manifestation_id,artifact_id,source_path_raw,source_record_key_raw,
              observed_utc,manifestation_metadata_json
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                _artifact_id("manifestation", shot_artifact),
                shot_artifact,
                str(screenshot["rel_path"]),
                str(screenshot["screenshot_id"]),
                "operator-local",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO swk_artifact_manifestation(
              manifestation_id,artifact_id,source_path_raw,source_record_key_raw,
              observed_utc,manifestation_metadata_json
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                _artifact_id("manifestation", mfl_artifact),
                mfl_artifact,
                "mfl-read-only",
                str(mfl["corpus_record_id"]),
                "operator-local",
                json.dumps(
                    {"corpus_uid": mfl["corpus_uid"], "snapshot_id": mfl["snapshot_id"]},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )

        subject_id = f"binding-{candidate_id[:24]}"
        state = (
            "PASS"
            if decision == "SAME_EVENT" and package_status == "PASS"
            else "CANDIDATE_NOT_IDENTITY"
        )
        conn.execute(
            """
            INSERT INTO swk_subject_ref(
              subject_id,subject_kind,source_namespace,external_record_key_raw,
              source_snapshot_sha256,identity_state,binding_basis_json,created_utc
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                subject_id,
                "RECONSTRUCTED_FLIGHT",
                "SKYWATCHER_PRIMARY",
                candidate_id,
                input_sha,
                state,
                json.dumps(
                    {
                        "decision": decision,
                        "decision_basis": row.get("decision_basis") or [],
                        "independent_evidence_refs": (
                            row.get("independent_evidence_refs") or []
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "operator-local",
            ),
        )
        for artifact_id in (shot_artifact, mfl_artifact):
            conn.execute(
                """
                INSERT INTO swk_subject_evidence(
                  subject_id,artifact_id,relation,binding_state,evidence_basis_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    subject_id,
                    artifact_id,
                    "CONTEXT",
                    "PASS" if decision != "UNRESOLVED" else "UNRESOLVED",
                    '{"role":"context-for-reviewed-binding"}',
                ),
            )

        implication_id = f"opimp-{candidate_id[:24]}"
        if decision == "SAME_EVENT":
            statement = (
                "Operator review adjudicates this screenshot observation and MFL "
                "record as the same bounded event."
            )
            implication_type = "LOCAL"
            delta_type = "CONFIRMS"
            cert_state = "OPEN"
        elif decision == "DIFFERENT_EVENT":
            statement = (
                "Operator review rejects this screenshot observation and MFL "
                "record as the same event."
            )
            implication_type = "CONTRADICTION"
            delta_type = "CONTRADICTS"
            cert_state = "OPEN"
        else:
            statement = (
                "The screenshot-to-MFL event binding remains unresolved after "
                "operator review."
            )
            implication_type = "LOCAL"
            delta_type = "NO_MATERIAL_CHANGE"
            cert_state = "UNRESOLVED"

        dep_hash = sha256_canonical(
            {
                "candidate_id": candidate_id,
                "review_sha256": review_sha256,
                "decision": decision,
            }
        )
        conn.execute(
            """
            INSERT INTO swk_implication(
              implication_id,run_id,analysis_owner,domain_scope_json,
              implication_type,epistemic_class,delta_type,statement,scope_json,
              limitations_json,alternatives_json,falsifiers_json,ruleset_version,
              dependency_sha256,validity_state,certification_state,created_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                implication_id,
                run_id,
                "FPIM",
                '{"scope_mode":"PHYSICAL","domains":["AIR"]}',
                implication_type,
                "INFERENCE",
                delta_type,
                statement,
                json.dumps({"candidate_id": candidate_id}, separators=(",", ":")),
                json.dumps(
                    [
                        "same-event adjudication does not establish mission",
                        "same-event adjudication does not establish operator identity",
                        "canonical MFL rows remain unchanged",
                    ],
                    separators=(",", ":"),
                ),
                "[]",
                "[]",
                SCHEMA_VERSION,
                dep_hash,
                "CURRENT",
                cert_state,
                "operator-local",
            ),
        )
        conn.execute(
            """
            INSERT INTO swk_implication_evidence(
              implication_id,artifact_id,evidence_role
            ) VALUES(?,?,?)
            """,
            (implication_id, review_artifact, "SUPPORT"),
        )
        for artifact_id in (shot_artifact, mfl_artifact):
            conn.execute(
                """
                INSERT INTO swk_implication_evidence(
                  implication_id,artifact_id,evidence_role
                ) VALUES(?,?,?)
                """,
                (implication_id, artifact_id, "CONTEXT"),
            )
        conn.execute(
            """
            INSERT INTO swk_implication_subject(
              implication_id,subject_id,subject_role
            ) VALUES(?,?,?)
            """,
            (implication_id, subject_id, "ABOUT"),
        )
        if package_status == "PASS" and decision in {"SAME_EVENT", "DIFFERENT_EVENT"}:
            conn.execute(
                """
                UPDATE swk_implication
                SET certification_state='PASS'
                WHERE implication_id=?
                """,
                (implication_id,),
            )

    source_count = int(
        conn.execute("SELECT COUNT(*) FROM swk_artifact_manifestation").fetchone()[0]
    )
    unresolved = sum(1 for row in reviewed_rows if row["decision"] == "UNRESOLVED")
    implications = int(
        conn.execute("SELECT COUNT(*) FROM swk_implication").fetchone()[0]
    )
    state_manifest = sha256_canonical(
        {
            "input_manifest_sha256": input_sha,
            "source_manifestation_count": source_count,
            "unresolved_candidate_count": unresolved,
            "implication_count": implications,
        }
    )
    state_id = f"opstate-{state_manifest[:20]}"
    state_cert = "PASS" if package_status == "PASS" else "BLOCKED"
    conn.execute(
        """
        INSERT INTO swk_knowledge_state(
          state_id,run_id,source_manifestation_count,canonical_event_count,
          canonical_denominator_ref,canonical_denominator_sha256,
          canonical_denominator_cert_receipt,unresolved_candidate_count,
          implication_count,contradiction_count,state_manifest_sha256,
          certification_state,created_utc
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state_id,
            run_id,
            source_count,
            None,
            "MFL_DB_READ_ONLY",
            mfl_db_sha256,
            input_sha,
            unresolved,
            implications,
            0,
            state_manifest,
            state_cert,
            "operator-local",
        ),
    )
    conn.execute(
        "UPDATE swk_knowledge_run SET status=?, finished_utc=? WHERE run_id=?",
        (
            "VALIDATED" if package_status == "PASS" else "BLOCKED",
            "operator-local",
            run_id,
        ),
    )
    conn.commit()
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        conn.close()
        raise OperatorCertificationError("scratch sidecar foreign-key check failed")
    counts = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in (
            "swk_source_artifact",
            "swk_artifact_manifestation",
            "swk_subject_ref",
            "swk_implication",
            "swk_knowledge_state",
        )
    }
    conn.close()
    return {
        "path": str(sidecar_path),
        "sha256": sha256_file(sidecar_path),
        "run_id": run_id,
        "state_id": state_id,
        "counts": counts,
        "reused_identical_inputs": False,
        "canonical_event_count_claimed": False,
        "migration_0004_registered": False,
    }


def certify_operator_package(
    *,
    repo_root: Path,
    rlsm_db: Path,
    mfl_db: Path,
    corpus_root: Path,
    gold_path: Path,
    review_path: Path,
    output_dir: Path,
    expected_git_sha: str | None = None,
    audit_runner: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_bytes = review_path.read_bytes()
    review_sha_before = hashlib.sha256(review_bytes).hexdigest()
    frozen_review_path = output_dir / "binding_review.frozen.jsonl"
    frozen_review_path.write_bytes(review_bytes)
    before = preflight(
        repo_root=repo_root,
        rlsm_db=rlsm_db,
        mfl_db=mfl_db,
        corpus_root=corpus_root,
        gold_path=gold_path,
        expected_git_sha=expected_git_sha,
    )
    candidates, candidate_manifest = discover_binding_candidates(
        rlsm_db,
        mfl_db,
        gold_path,
    )
    binding_metrics, binding_errors = validate_binding_review(
        frozen_review_path,
        candidates,
    )

    if audit_runner is None:
        from fr24 import rlsm_intelligence_audit_v2

        audit_runner = rlsm_intelligence_audit_v2.run

    audit_dir = output_dir / "rlsm_audit"
    audit = dict(
        audit_runner(
            db_path=rlsm_db,
            corpus_root=corpus_root,
            gold_path=gold_path,
            outputs_dir=audit_dir,
            sample_limit=25,
        )
    )
    audit_status = str(audit.get("certification_status") or "BLOCKED")

    gold_after, _ = validate_gold_review(
        rlsm_db,
        gold_path,
        corpus_root=corpus_root,
    )
    after_hashes = {
        "rlsm_db_sha256": sha256_file(rlsm_db),
        "rlsm_db_logical_sha256": sqlite_logical_sha256(rlsm_db),
        "mfl_db_sha256": sha256_file(mfl_db),
        "mfl_db_logical_sha256": sqlite_logical_sha256(mfl_db),
        "gold_sha256": sha256_file(gold_path),
        "review_sha256": sha256_file(review_path),
    }
    stable = (
        before["rlsm_db_sha256"] == after_hashes["rlsm_db_sha256"]
        and before["rlsm_db_logical_sha256"]
        == after_hashes["rlsm_db_logical_sha256"]
        and before["mfl_db_sha256"] == after_hashes["mfl_db_sha256"]
        and before["mfl_db_logical_sha256"]
        == after_hashes["mfl_db_logical_sha256"]
        and before["gold_sha256"] == after_hashes["gold_sha256"]
        and review_sha_before == after_hashes["review_sha256"]
        and before["gold_review"].get("source_manifest_sha256")
        == gold_after.get("source_manifest_sha256")
        and gold_after["status"] == "PASS"
    )

    status = "PASS"
    if not stable:
        status = "UNRESOLVED"
    elif (
        before["gold_review"]["status"] != "PASS"
        or audit_status == "FAIL"
        or binding_metrics["status"] == "FAIL"
    ):
        status = "FAIL"
    elif audit_status != "PASS" or binding_metrics["status"] != "PASS":
        status = "BLOCKED"

    reviewed_by_id = {
        str(row["candidate_id"]): row for row in _load_records(frozen_review_path)
    }
    reviewed_rows = [
        reviewed_by_id[row["candidate_id"]]
        for row in candidates
        if row["candidate_id"] in reviewed_by_id
    ]
    sidecar_schema = (
        repo_root / "schemas" / "knowledge_implications_v1.sql"
    ).read_text(encoding="utf-8")
    if binding_metrics["status"] == "FAIL":
        sidecar = {
            "status": "NOT_MATERIALIZED",
            "reason": "binding_review_failed",
            "migration_0004_registered": False,
            "canonical_event_count_claimed": False,
        }
    else:
        sidecar = materialize_review_sidecar(
            sidecar_path=output_dir / "operator_sidecar.sqlite",
            schema_sql=sidecar_schema,
            reviewed_rows=reviewed_rows,
            rlsm_db_sha256=after_hashes["rlsm_db_logical_sha256"],
            mfl_db_sha256=after_hashes["mfl_db_logical_sha256"],
            gold_sha256=after_hashes["gold_sha256"],
            review_sha256=review_sha_before,
            git_sha=before["git_sha"],
            package_status=status,
        )

    current_candidates_path = output_dir / "binding_candidates.recomputed.jsonl"
    current_manifest_path = output_dir / "binding_candidate_manifest.json"
    write_review_template(
        candidates,
        candidate_manifest,
        current_candidates_path,
        current_manifest_path,
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "certification_status": status,
        "git_sha": before["git_sha"],
        "inputs": {
            "rlsm_db": str(rlsm_db),
            "rlsm_db_sha256": after_hashes["rlsm_db_sha256"],
            "rlsm_db_logical_sha256": after_hashes["rlsm_db_logical_sha256"],
            "mfl_db": str(mfl_db),
            "mfl_db_sha256": after_hashes["mfl_db_sha256"],
            "mfl_db_logical_sha256": after_hashes["mfl_db_logical_sha256"],
            "gold_path": str(gold_path),
            "gold_sha256": after_hashes["gold_sha256"],
            "review_path": str(review_path),
            "review_sha256": after_hashes["review_sha256"],
            "frozen_review_path": str(frozen_review_path),
            "frozen_review_sha256": review_sha_before,
            "corpus_root": str(corpus_root),
            "inputs_stable_during_certification": stable,
        },
        "gold_review": before["gold_review"],
        "rlsm_audit": {
            "certification_status": audit_status,
            "required_gates": audit.get("required_gates"),
            "gates": audit.get("gates"),
            "error_count": audit.get("error_count"),
        },
        "binding_candidate_manifest": candidate_manifest,
        "binding_review": binding_metrics,
        "binding_review_errors": binding_errors,
        "sidecar": sidecar,
        "claims": {
            "candidate_discovery_exhaustive_within_declared_rules": True,
            "candidate_discovery_universal": False,
            "canonical_event_count_changed": False,
            "canonical_mfl_mutation_authorized": False,
            "migration_0004_registered": False,
            "mission_or_intent_established": False,
        },
    }
    report_path = output_dir / "operator_certification_report.json"
    markdown_path = output_dir / "operator_certification_report.md"
    report["outputs"] = {
        "json": str(report_path),
        "markdown": str(markdown_path),
        "sidecar": (
            str(output_dir / "operator_sidecar.sqlite")
            if sidecar.get("path")
            else None
        ),
        "frozen_review": str(frozen_review_path),
        "candidate_manifest": str(current_manifest_path),
        "candidate_rows": str(current_candidates_path),
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join(
            [
                "# Operator corpus certification",
                "",
                f"- Status: **{status}**",
                f"- Git SHA: {before['git_sha']}",
                f"- Gold review: **{before['gold_review']['status']}**",
                f"- RLSM audit: **{audit_status}**",
                f"- Candidate rows: **{candidate_manifest['candidate_count']}**",
                f"- Same-event decisions: **{binding_metrics['same_event']}**",
                f"- Different-event decisions: **{binding_metrics['different_event']}**",
                f"- Unresolved decisions: **{binding_metrics['unresolved']}**",
                f"- Inputs stable: **{stable}**",
                "- Canonical MFL mutation: **NOT AUTHORIZED**",
                "- Migration 0004: **NOT REGISTERED**",
                "- Canonical event count delta: **NOT CLAIMED**",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report
