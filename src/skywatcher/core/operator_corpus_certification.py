"""Operator-local certification package for the cumulative implication sidecar.

This module is read-only against the operator RLSM and canonical MFL databases.
It snapshots both stores, runs the existing RLSM v2 audit against the snapshot,
builds a discovery-only screenshot↔MFL candidate denominator, and validates a
separately reviewed adjudication file. Migration 0004 is never registered here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from skywatcher.fr24 import database_migrations as migrations

SCHEMA_VERSION = "skywatcher.knowledge.operator-certification.v1"
EXPECTED_GOLD_RECORDS = 300
ALLOWED_DECISIONS = {"SAME_EVENT", "DISTINCT_EVENT", "UNRESOLVED"}
ALLOWED_CONTROL_ROLES = {"NONE", "POSITIVE_CONTROL", "NEGATIVE_CONTROL"}
STRONG_SAME_EVENT_BASES = {
    "AUTHORITATIVE_SOURCE_BINDING",
    "INDEPENDENT_EVENT_ID_BINDING",
    "SOURCE_FLIGHT_ID_EXACT_WITH_TEMPORAL_CORROBORATION",
    "FILE_BACKED_TRACK_TIME_CONTINUITY",
    "MANUAL_PRIMARY_SOURCE_BINDING",
}
STRONG_DISTINCT_EVENT_BASES = {
    "AUTHORITATIVE_DIFFERENT_EVENT_BINDING",
    "CONTRADICTORY_SOURCE_FLIGHT_ID",
    "DISJOINT_TIME_INTERVALS",
    "FILE_BACKED_TRACK_DISCONTINUITY",
    "MANUAL_PRIMARY_SOURCE_DIFFERENT_EVENT",
}


class OperatorCertificationError(RuntimeError):
    """Raised when an operator-corpus certification invariant fails."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(_canonical_json(dict(row)) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OperatorCertificationError(
                f"{path.name} line {line_number} is invalid JSON: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise OperatorCertificationError(
                f"{path.name} line {line_number} is not an object"
            )
        rows.append(value)
    return rows


def _gold_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.casefold()
    if suffix == ".jsonl":
        return _read_jsonl(path)
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise OperatorCertificationError("gold JSON must be an array of objects")
        return list(value)
    raise OperatorCertificationError("gold sample must be .json or .jsonl")


def _git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OperatorCertificationError("cannot resolve repository HEAD") from exc
    value = result.stdout.strip()
    if len(value) != 40:
        raise OperatorCertificationError("repository HEAD is not a full SHA-1")
    return value


def _require_checkpoint(repo_root: Path, expected_commit: str) -> str:
    if len(expected_commit) != 40:
        raise OperatorCertificationError("--expected-commit must be a full 40-character SHA")
    actual = _git_head(repo_root)
    if actual != expected_commit:
        raise OperatorCertificationError(
            f"repository HEAD mismatch: expected {expected_commit}, found {actual}"
        )
    versions = [migration.version for migration in migrations.MIGRATIONS]
    if versions != [1, 2, 3] or migrations.LATEST_VERSION != 3:
        raise OperatorCertificationError(
            "migration ledger changed; operator package requires 0004 NOT_REGISTERED"
        )
    return actual


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise OperatorCertificationError(f"database not found: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _snapshot_sqlite(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise OperatorCertificationError(f"snapshot destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = _open_readonly(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        dst.commit()
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise OperatorCertificationError(
                f"snapshot integrity_check failed for {source}: {integrity}"
            )
        fk_rows = dst.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise OperatorCertificationError(
                f"snapshot foreign_key_check failed for {source}: {len(fk_rows)} rows"
            )
    finally:
        dst.close()
        src.close()
    return {
        "source_path": str(source.resolve()),
        "snapshot_path": destination.name,
        "sha256": _sha256_file(destination),
        "size_bytes": destination.stat().st_size,
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    }


def _assert_mfl_snapshot_contract(mfl_snapshot: Path) -> dict[str, Any]:
    conn = _open_readonly(mfl_snapshot)
    try:
        tables = _table_names(conn)
        required = {
            "schema_version",
            "flight_corpus_snapshots",
            "flight_corpus_records",
            "flight_source_manifestations",
        }
        missing = sorted(required - tables)
        if missing:
            raise OperatorCertificationError(
                "MFL snapshot missing required tables: " + ", ".join(missing)
            )
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if int(version or 0) != 3:
            raise OperatorCertificationError(
                f"MFL snapshot schema version must be 3, found {version}"
            )
        sidecar = sorted(name for name in tables if name.startswith("swk_"))
        if sidecar:
            raise OperatorCertificationError(
                "operator MFL snapshot already contains sidecar tables: "
                + ", ".join(sidecar)
            )
        records = int(conn.execute("SELECT COUNT(*) FROM flight_corpus_records").fetchone()[0])
        snapshots = int(
            conn.execute("SELECT COUNT(*) FROM flight_corpus_snapshots").fetchone()[0]
        )
        return {
            "schema_version": 3,
            "corpus_records": records,
            "corpus_snapshots": snapshots,
            "migration_0004_registered": False,
            "sidecar_tables_present": False,
        }
    finally:
        conn.close()


def _assert_rlsm_snapshot_contract(rlsm_snapshot: Path) -> dict[str, Any]:
    conn = _open_readonly(rlsm_snapshot)
    try:
        tables = _table_names(conn)
        required = {"screenshots", "aircraft_observations"}
        missing = sorted(required - tables)
        if missing:
            raise OperatorCertificationError(
                "RLSM snapshot missing required tables: " + ", ".join(missing)
            )
        screenshots = int(conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0])
        aircraft = int(
            conn.execute("SELECT COUNT(*) FROM aircraft_observations").fetchone()[0]
        )
        return {"screenshots": screenshots, "aircraft_observations": aircraft}
    finally:
        conn.close()


def _resolve_repo_source(repo_root: Path, rel_path: str) -> Path:
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise OperatorCertificationError(f"unsafe RLSM rel_path: {rel_path}")
    return repo_root / rel


def _verify_gold_source_bytes(
    *,
    repo_root: Path,
    rlsm_snapshot: Path,
    gold_path: Path,
) -> dict[str, Any]:
    rows = _gold_rows(gold_path)
    if len(rows) != EXPECTED_GOLD_RECORDS:
        return {
            "status": "BLOCKED",
            "records": len(rows),
            "expected_records": EXPECTED_GOLD_RECORDS,
            "verified": 0,
            "failures": [{"reason": "gold_sample_wrong_size"}],
        }

    conn = _open_readonly(rlsm_snapshot)
    failures: list[dict[str, Any]] = []
    verified = 0
    resolved_ids: set[int] = set()
    try:
        for index, gold in enumerate(rows):
            matches: dict[int, sqlite3.Row] = {}
            if gold.get("screenshot_id") is not None:
                row = conn.execute(
                    "SELECT screenshot_id,sha256,filename,rel_path FROM screenshots "
                    "WHERE screenshot_id=?",
                    (gold["screenshot_id"],),
                ).fetchone()
                if row is not None:
                    matches[int(row["screenshot_id"])] = row
            if gold.get("screenshot_sha256"):
                for row in conn.execute(
                    "SELECT screenshot_id,sha256,filename,rel_path FROM screenshots "
                    "WHERE LOWER(sha256)=LOWER(?)",
                    (gold["screenshot_sha256"],),
                ):
                    matches[int(row["screenshot_id"])] = row
            if gold.get("filename"):
                for row in conn.execute(
                    "SELECT screenshot_id,sha256,filename,rel_path FROM screenshots "
                    "WHERE filename=?",
                    (gold["filename"],),
                ):
                    matches[int(row["screenshot_id"])] = row

            if len(matches) != 1:
                failures.append(
                    {
                        "index": index,
                        "reason": "gold_identity_not_exactly_one_rlsm_row",
                        "match_count": len(matches),
                    }
                )
                continue
            screenshot_id, row = next(iter(matches.items()))
            if screenshot_id in resolved_ids:
                failures.append(
                    {
                        "index": index,
                        "reason": "duplicate_gold_screenshot",
                        "screenshot_id": screenshot_id,
                    }
                )
                continue
            resolved_ids.add(screenshot_id)

            if gold.get("screenshot_sha256") and str(gold["screenshot_sha256"]).casefold() != str(
                row["sha256"]
            ).casefold():
                failures.append(
                    {
                        "index": index,
                        "reason": "gold_sha_disagrees_with_rlsm",
                        "screenshot_id": screenshot_id,
                    }
                )
                continue

            annotator = str(gold.get("annotator") or "").strip()
            reviewer = str(gold.get("reviewed_by") or "").strip()
            if not annotator or not reviewer or annotator.casefold() == reviewer.casefold():
                failures.append(
                    {
                        "index": index,
                        "reason": "independent_review_not_established",
                        "screenshot_id": screenshot_id,
                    }
                )
                continue
            if "labels" not in gold or not isinstance(gold.get("labels"), list):
                failures.append(
                    {
                        "index": index,
                        "reason": "labels_not_explicit",
                        "screenshot_id": screenshot_id,
                    }
                )
                continue

            source = _resolve_repo_source(repo_root, str(row["rel_path"]))
            if not source.is_file():
                failures.append(
                    {
                        "index": index,
                        "reason": "source_missing",
                        "screenshot_id": screenshot_id,
                        "rel_path": row["rel_path"],
                    }
                )
                continue
            digest = _sha256_file(source)
            if digest.casefold() != str(row["sha256"]).casefold():
                failures.append(
                    {
                        "index": index,
                        "reason": "source_sha_mismatch",
                        "screenshot_id": screenshot_id,
                        "rel_path": row["rel_path"],
                    }
                )
                continue
            verified += 1
    finally:
        conn.close()

    return {
        "status": "PASS" if verified == EXPECTED_GOLD_RECORDS and not failures else "FAIL",
        "records": len(rows),
        "expected_records": EXPECTED_GOLD_RECORDS,
        "verified": verified,
        "failures": failures,
    }


def _run_rlsm_audit(
    *,
    rlsm_snapshot: Path,
    corpus_root: Path,
    gold_path: Path,
    outputs_dir: Path,
) -> dict[str, Any]:
    try:
        from fr24 import rlsm_intelligence_audit_v2 as audit_v2
    except ImportError as exc:
        raise OperatorCertificationError(
            "cannot import fr24.rlsm_intelligence_audit_v2; run with PYTHONPATH=src:."
        ) from exc
    outputs_dir.mkdir(parents=True, exist_ok=True)
    report = audit_v2.run(
        db_path=rlsm_snapshot,
        corpus_root=corpus_root,
        gold_path=gold_path,
        outputs_dir=outputs_dir,
        sample_limit=25,
    )
    return report


def _staging_candidates(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise OperatorCertificationError("staging export must contain an items array")
    by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        sha = str(item.get("screenshot_sha256") or "").casefold()
        if not sha:
            continue
        for candidate in item.get("candidate_links") or []:
            if isinstance(candidate, dict):
                by_sha[sha].append(candidate)
    return dict(by_sha)


def _build_candidate_packet(
    *,
    rlsm_snapshot: Path,
    mfl_snapshot: Path,
    staging_export: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    staged = _staging_candidates(staging_export)
    rlsm = _open_readonly(rlsm_snapshot)
    mfl = _open_readonly(mfl_snapshot)
    packet: list[dict[str, Any]] = []
    template: list[dict[str, Any]] = []
    screenshots_seen = 0
    pair_count = 0
    zero_candidate = 0
    try:
        screenshot_rows = rlsm.execute(
            """
            SELECT screenshot_id,sha256,filename,filename_ts
            FROM screenshots
            WHERE ingest_status='ok'
            ORDER BY screenshot_id
            """
        ).fetchall()

        for screenshot in screenshot_rows:
            callsigns = sorted(
                {
                    str(row[0]).strip()
                    for row in rlsm.execute(
                        """
                        SELECT callsign FROM aircraft_observations
                        WHERE screenshot_id=?
                          AND callsign IS NOT NULL
                          AND TRIM(callsign)<>''
                        """,
                        (screenshot["screenshot_id"],),
                    ).fetchall()
                    if str(row[0]).strip()
                }
            )
            registrations = sorted(
                {
                    str(row[0]).strip()
                    for row in rlsm.execute(
                        """
                        SELECT registration FROM aircraft_observations
                        WHERE screenshot_id=?
                          AND registration IS NOT NULL
                          AND TRIM(registration)<>''
                        """,
                        (screenshot["screenshot_id"],),
                    ).fetchall()
                    if str(row[0]).strip()
                }
            )
            candidate_map: dict[int, dict[str, Any]] = {}

            for callsign in callsigns:
                for row in mfl.execute(
                    """
                    SELECT corpus_record_id,snapshot_id,corpus_uid,
                           source_flight_id_raw,callsign_raw,start_time_utc,end_time_utc
                    FROM flight_corpus_records
                    WHERE UPPER(TRIM(callsign_raw))=UPPER(TRIM(?))
                    ORDER BY snapshot_id,corpus_record_id
                    """,
                    (callsign,),
                ).fetchall():
                    record_id = int(row["corpus_record_id"])
                    candidate = candidate_map.setdefault(
                        record_id,
                        {
                            **dict(row),
                            "match_basis": [],
                            "association_status": "CANDIDATE_NOT_IDENTITY",
                        },
                    )
                    if "EXACT_RLSM_CALLSIGN_DISCOVERY" not in candidate["match_basis"]:
                        candidate["match_basis"].append("EXACT_RLSM_CALLSIGN_DISCOVERY")

            sha = str(screenshot["sha256"]).casefold()
            for candidate in staged.get(sha, []):
                record_id = candidate.get("corpus_record_id")
                if isinstance(record_id, bool) or not isinstance(record_id, int):
                    continue
                existing = mfl.execute(
                    """
                    SELECT corpus_record_id,snapshot_id,corpus_uid,
                           source_flight_id_raw,callsign_raw,start_time_utc,end_time_utc
                    FROM flight_corpus_records WHERE corpus_record_id=?
                    """,
                    (record_id,),
                ).fetchone()
                if existing is None:
                    continue
                entry = candidate_map.setdefault(
                    record_id,
                    {
                        **dict(existing),
                        "match_basis": [],
                        "association_status": "CANDIDATE_NOT_IDENTITY",
                    },
                )
                for basis in candidate.get("match_basis") or ["SCREENSHOT_PROCESSOR_STAGING"]:
                    basis_text = str(basis)
                    if basis_text not in entry["match_basis"]:
                        entry["match_basis"].append(basis_text)

            screenshots_seen += 1
            candidates = sorted(
                candidate_map.values(),
                key=lambda row: (int(row["snapshot_id"]), int(row["corpus_record_id"])),
            )
            if not candidates:
                zero_candidate += 1
                continue

            packet_row = {
                "schema_version": "skywatcher.operator.identity-candidates.v1",
                "screenshot_id": int(screenshot["screenshot_id"]),
                "screenshot_sha256": str(screenshot["sha256"]),
                "filename_raw": str(screenshot["filename"]),
                "filename_timestamp_raw": screenshot["filename_ts"],
                "rlsm_callsign_candidates": callsigns,
                "rlsm_registration_candidates": registrations,
                "rlsm_identity_state": (
                    "CONFLICTING"
                    if len(callsigns) > 1 or len(registrations) > 1
                    else "CANDIDATE_NOT_IDENTITY"
                ),
                "candidate_records": candidates,
                "candidate_count": len(candidates),
            }
            packet.append(packet_row)
            for candidate in candidates:
                key = (
                    f"{screenshot['sha256']}|{candidate['snapshot_id']}|"
                    f"{candidate['corpus_record_id']}"
                )
                pair_id = _sha256_bytes(key.encode("utf-8"))[:32]
                template.append(
                    {
                        "schema_version": "skywatcher.operator.event-adjudication.v1",
                        "pair_id": pair_id,
                        "screenshot_id": int(screenshot["screenshot_id"]),
                        "screenshot_sha256": str(screenshot["sha256"]),
                        "mfl_snapshot_id": int(candidate["snapshot_id"]),
                        "mfl_corpus_record_id": int(candidate["corpus_record_id"]),
                        "mfl_corpus_uid": candidate["corpus_uid"],
                        "candidate_match_basis": list(candidate["match_basis"]),
                        "review_state": "UNREVIEWED",
                        "decision": "UNRESOLVED",
                        "identity_basis": [],
                        "evidence_refs": [],
                        "control_role": "NONE",
                        "reviewer_id": "",
                        "notes": "",
                    }
                )
                pair_count += 1
    finally:
        rlsm.close()
        mfl.close()

    return (
        packet,
        template,
        {
            "screenshots_considered": screenshots_seen,
            "screenshots_with_candidates": len(packet),
            "screenshots_without_candidates": zero_candidate,
            "candidate_pairs": pair_count,
        },
    )


def _artifact_manifest(paths: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        result[name] = {
            "path": path.name if path.parent.name == "inputs" else path.as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return result


def prepare_package(
    *,
    repo_root: Path,
    rlsm_db: Path,
    mfl_db: Path,
    corpus_root: Path,
    gold_path: Path,
    output_dir: Path,
    expected_commit: str,
    staging_export: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    actual_commit = _require_checkpoint(repo_root, expected_commit)
    for path, label in (
        (rlsm_db, "RLSM database"),
        (mfl_db, "MFL database"),
        (gold_path, "gold sample"),
    ):
        if not path.is_file():
            raise OperatorCertificationError(f"{label} not found: {path}")
    if not corpus_root.is_dir():
        raise OperatorCertificationError(f"corpus root not found: {corpus_root}")
    if staging_export is not None and not staging_export.is_file():
        raise OperatorCertificationError(f"staging export not found: {staging_export}")
    if output_dir.exists():
        raise OperatorCertificationError(
            f"output directory already exists; no overwrite allowed: {output_dir}"
        )

    inputs = output_dir / "inputs"
    audit_dir = output_dir / "rlsm_audit"
    output_dir.mkdir(parents=True)
    inputs.mkdir()

    rlsm_snapshot = inputs / "rlsm.snapshot.sqlite"
    mfl_snapshot = inputs / "mfl.snapshot.sqlite"
    rlsm_snapshot_receipt = _snapshot_sqlite(rlsm_db, rlsm_snapshot)
    mfl_snapshot_receipt = _snapshot_sqlite(mfl_db, mfl_snapshot)
    rlsm_contract = _assert_rlsm_snapshot_contract(rlsm_snapshot)
    mfl_contract = _assert_mfl_snapshot_contract(mfl_snapshot)

    audit = _run_rlsm_audit(
        rlsm_snapshot=rlsm_snapshot,
        corpus_root=corpus_root.resolve(),
        gold_path=gold_path.resolve(),
        outputs_dir=audit_dir,
    )
    gold_bytes = _verify_gold_source_bytes(
        repo_root=repo_root,
        rlsm_snapshot=rlsm_snapshot,
        gold_path=gold_path,
    )

    packet, template, candidate_counts = _build_candidate_packet(
        rlsm_snapshot=rlsm_snapshot,
        mfl_snapshot=mfl_snapshot,
        staging_export=staging_export,
    )
    packet_path = output_dir / "identity_candidates.jsonl"
    template_path = output_dir / "adjudication_template.jsonl"
    _write_jsonl(packet_path, packet)
    _write_jsonl(template_path, template)

    gold_copy = inputs / ("gold_sample" + gold_path.suffix.casefold())
    gold_copy.write_bytes(gold_path.read_bytes())
    staging_copy: Path | None = None
    if staging_export is not None:
        staging_copy = inputs / "screenshot_mfl_staging.json"
        staging_copy.write_bytes(staging_export.read_bytes())

    artifact_paths: dict[str, Path] = {
        "rlsm_snapshot": rlsm_snapshot,
        "mfl_snapshot": mfl_snapshot,
        "gold_sample": gold_copy,
        "identity_candidates": packet_path,
        "adjudication_template": template_path,
        "rlsm_audit": Path(audit["outputs"]["json"]),
    }
    if staging_copy is not None:
        artifact_paths["screenshot_mfl_staging"] = staging_copy

    status = (
        "READY_FOR_ADJUDICATION"
        if audit.get("certification_status") == "PASS" and gold_bytes["status"] == "PASS"
        else "BLOCKED"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository_commit": actual_commit,
        "preparation_status": status,
        "migration_0004_registered": False,
        "normal_startup_sidecar_enabled": False,
        "source_databases_mutated": False,
        "rlsm_snapshot": rlsm_snapshot_receipt,
        "mfl_snapshot": mfl_snapshot_receipt,
        "rlsm_contract": rlsm_contract,
        "mfl_contract": mfl_contract,
        "rlsm_audit_status": audit.get("certification_status"),
        "rlsm_required_gates": audit.get("required_gates", []),
        "gold_source_byte_identity": gold_bytes,
        "candidate_counts": candidate_counts,
        "candidate_semantics": "DISCOVERY_ONLY_CANDIDATE_NOT_IDENTITY",
        "artifacts": _artifact_manifest(artifact_paths),
    }
    manifest_path = output_dir / "operator_input_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest


def _load_package_manifest(package_dir: Path, expected_commit: str, repo_root: Path) -> dict[str, Any]:
    _require_checkpoint(repo_root.resolve(), expected_commit)
    path = package_dir / "operator_input_manifest.json"
    if not path.is_file():
        raise OperatorCertificationError("operator_input_manifest.json is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("repository_commit") != expected_commit:
        raise OperatorCertificationError("package repository commit does not match expected commit")
    if manifest.get("migration_0004_registered") is not False:
        raise OperatorCertificationError("package indicates migration 0004 registration")
    if manifest.get("source_databases_mutated") is not False:
        raise OperatorCertificationError("package does not certify read-only source handling")
    for name, info in (manifest.get("artifacts") or {}).items():
        raw_path = info.get("path")
        if not isinstance(raw_path, str):
            raise OperatorCertificationError(f"artifact path missing for {name}")
        candidate = (
            package_dir / "inputs" / raw_path
            if name in {"rlsm_snapshot", "mfl_snapshot", "gold_sample", "screenshot_mfl_staging"}
            else package_dir / raw_path
        )
        if not candidate.is_file():
            raise OperatorCertificationError(f"package artifact missing: {name}")
        if _sha256_file(candidate) != info.get("sha256"):
            raise OperatorCertificationError(f"package artifact hash mismatch: {name}")
    return manifest


def verify_adjudications(
    *,
    repo_root: Path,
    package_dir: Path,
    adjudications_path: Path,
    expected_commit: str,
) -> dict[str, Any]:
    manifest = _load_package_manifest(package_dir, expected_commit, repo_root)
    if manifest.get("preparation_status") != "READY_FOR_ADJUDICATION":
        raise OperatorCertificationError(
            "package preparation is not READY_FOR_ADJUDICATION"
        )
    template = _read_jsonl(package_dir / "adjudication_template.jsonl")
    reviewed = _read_jsonl(adjudications_path)

    expected = {str(row["pair_id"]): row for row in template}
    actual: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(reviewed):
        pair_id = str(row.get("pair_id") or "")
        if not pair_id or pair_id in actual:
            errors.append({"index": index, "reason": "missing_or_duplicate_pair_id"})
            continue
        actual[pair_id] = row

    if set(actual) != set(expected):
        errors.append(
            {
                "reason": "adjudication_denominator_mismatch",
                "missing_pair_ids": sorted(set(expected) - set(actual)),
                "extra_pair_ids": sorted(set(actual) - set(expected)),
            }
        )

    same_by_screenshot: dict[str, list[str]] = defaultdict(list)
    same = distinct = unresolved = positive_controls = negative_controls = 0
    certified_rows: list[dict[str, Any]] = []

    for pair_id in sorted(set(expected) & set(actual)):
        source = expected[pair_id]
        row = actual[pair_id]
        immutable = (
            "screenshot_id",
            "screenshot_sha256",
            "mfl_snapshot_id",
            "mfl_corpus_record_id",
            "mfl_corpus_uid",
        )
        for field in immutable:
            if row.get(field) != source.get(field):
                errors.append(
                    {"pair_id": pair_id, "reason": "candidate_identity_field_changed", "field": field}
                )

        if row.get("review_state") != "REVIEWED":
            errors.append({"pair_id": pair_id, "reason": "review_state_not_REVIEWED"})
        decision = row.get("decision")
        if decision not in ALLOWED_DECISIONS:
            errors.append({"pair_id": pair_id, "reason": "invalid_decision"})
            continue
        control = row.get("control_role", "NONE")
        if control not in ALLOWED_CONTROL_ROLES:
            errors.append({"pair_id": pair_id, "reason": "invalid_control_role"})
        reviewer = str(row.get("reviewer_id") or "").strip()
        if not reviewer:
            errors.append({"pair_id": pair_id, "reason": "reviewer_id_required"})

        basis = row.get("identity_basis")
        refs = row.get("evidence_refs")
        if not isinstance(basis, list) or not all(isinstance(item, str) for item in basis):
            errors.append({"pair_id": pair_id, "reason": "identity_basis_must_be_string_array"})
            basis = []
        if not isinstance(refs, list) or not all(isinstance(item, str) and item for item in refs):
            errors.append({"pair_id": pair_id, "reason": "evidence_refs_must_be_nonempty_strings"})
            refs = []

        if decision == "SAME_EVENT":
            same += 1
            same_by_screenshot[str(source["screenshot_sha256"])].append(pair_id)
            if not (set(basis) & STRONG_SAME_EVENT_BASES):
                errors.append({"pair_id": pair_id, "reason": "same_event_lacks_strong_identity_basis"})
            if not refs:
                errors.append({"pair_id": pair_id, "reason": "same_event_lacks_independent_evidence_ref"})
            if control == "POSITIVE_CONTROL":
                positive_controls += 1
            elif control == "NEGATIVE_CONTROL":
                errors.append({"pair_id": pair_id, "reason": "same_event_cannot_be_negative_control"})
            certified_rows.append(
                {
                    "schema_version": "skywatcher.operator.certified-binding.v1",
                    "pair_id": pair_id,
                    "screenshot_sha256": source["screenshot_sha256"],
                    "mfl_snapshot_id": source["mfl_snapshot_id"],
                    "mfl_corpus_record_id": source["mfl_corpus_record_id"],
                    "mfl_corpus_uid": source["mfl_corpus_uid"],
                    "identity_basis": basis,
                    "evidence_refs": refs,
                    "reviewer_id": reviewer,
                    "certification_scope": "REVIEWED_OPERATOR_BINDING_ONLY",
                    "canonical_mfl_mutation_authorized": False,
                }
            )
        elif decision == "DISTINCT_EVENT":
            distinct += 1
            if not (set(basis) & STRONG_DISTINCT_EVENT_BASES):
                errors.append({"pair_id": pair_id, "reason": "distinct_event_lacks_strong_identity_basis"})
            if not refs:
                errors.append({"pair_id": pair_id, "reason": "distinct_event_lacks_evidence_ref"})
            if control == "NEGATIVE_CONTROL":
                negative_controls += 1
            elif control == "POSITIVE_CONTROL":
                errors.append({"pair_id": pair_id, "reason": "distinct_event_cannot_be_positive_control"})
        else:
            unresolved += 1
            if control != "NONE":
                errors.append({"pair_id": pair_id, "reason": "unresolved_cannot_be_control"})

    for screenshot_sha, pair_ids in same_by_screenshot.items():
        if len(pair_ids) > 1:
            errors.append(
                {
                    "reason": "one_screenshot_bound_to_multiple_mfl_events",
                    "screenshot_sha256": screenshot_sha,
                    "pair_ids": pair_ids,
                }
            )

    if errors:
        status = "FAIL"
    elif positive_controls == 0 or negative_controls == 0:
        status = "BLOCKED"
    elif unresolved:
        status = "PROVISIONAL"
    else:
        status = "PASS"

    review_dir = package_dir / "review"
    review_dir.mkdir(exist_ok=True)
    reviewed_copy = review_dir / "adjudications.jsonl"
    data = adjudications_path.read_bytes()
    if reviewed_copy.exists() and reviewed_copy.read_bytes() != data:
        raise OperatorCertificationError("review/adjudications.jsonl exists with different bytes")
    reviewed_copy.write_bytes(data)

    bindings_path = package_dir / "certified_bindings.jsonl"
    _write_jsonl(bindings_path, certified_rows)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "repository_commit": expected_commit,
        "certification_status": status,
        "migration_0004_registered": False,
        "canonical_mfl_mutation_authorized": False,
        "candidate_pair_denominator": len(expected),
        "reviewed_pair_rows": len(reviewed),
        "same_event": same,
        "distinct_event": distinct,
        "unresolved": unresolved,
        "positive_controls": positive_controls,
        "negative_controls": negative_controls,
        "certified_binding_rows": len(certified_rows),
        "errors": errors,
        "artifacts": {
            "operator_input_manifest_sha256": _sha256_file(
                package_dir / "operator_input_manifest.json"
            ),
            "adjudications_sha256": _sha256_file(reviewed_copy),
            "certified_bindings_sha256": _sha256_file(bindings_path),
        },
        "claim_boundary": (
            "PASS certifies only the frozen reviewed screenshot↔MFL binding denominator; "
            "it does not authorize canonical MFL mutation, mission inference, or migration 0004."
        ),
    }
    _write_json(package_dir / "certification_receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="freeze inputs and create adjudication packet")
    prepare.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare.add_argument("--rlsm-db", type=Path, required=True)
    prepare.add_argument("--mfl-db", type=Path, required=True)
    prepare.add_argument("--corpus-root", type=Path, required=True)
    prepare.add_argument("--gold", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--expected-commit", required=True)
    prepare.add_argument("--staging-export", type=Path, default=None)

    verify = sub.add_parser("verify", help="validate independently reviewed adjudications")
    verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify.add_argument("--package-dir", type=Path, required=True)
    verify.add_argument("--adjudications", type=Path, required=True)
    verify.add_argument("--expected-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_package(
                repo_root=args.repo_root,
                rlsm_db=args.rlsm_db,
                mfl_db=args.mfl_db,
                corpus_root=args.corpus_root,
                gold_path=args.gold,
                output_dir=args.out,
                expected_commit=args.expected_commit,
                staging_export=args.staging_export,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["preparation_status"] == "READY_FOR_ADJUDICATION" else 2

        result = verify_adjudications(
            repo_root=args.repo_root,
            package_dir=args.package_dir,
            adjudications_path=args.adjudications,
            expected_commit=args.expected_commit,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return {"PASS": 0, "PROVISIONAL": 3, "BLOCKED": 2, "FAIL": 1}[
            result["certification_status"]
        ]
    except (OperatorCertificationError, sqlite3.DatabaseError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
