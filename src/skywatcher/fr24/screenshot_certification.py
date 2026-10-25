"""Authenticated operator-local screenshot-intelligence certification controller.

This wraps the existing RLSM v2 audit without changing its scoring semantics.
Gold data stays beneath the local runtime vault. Canonical corpus tables remain
read-only. A certification receipt freezes the gold SHA-256, RLSM database
SHA-256, logical corpus-ledger manifestation, audit gates, and output hashes.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from fr24 import rlsm_intelligence_audit_v2 as audit_v2

MAX_GOLD_BYTES = 8 * 1024 * 1024
EXPECTED_GOLD_RECORDS = 300
SCHEMA_VERSION = "skywatcher.screenshot_certification.v1"
_AUDIT_LOCK = threading.Lock()


class ScreenshotCertificationError(RuntimeError):
    """Fail-closed certification controller error."""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_gold_bytes(name: str, payload: bytes) -> list[dict[str, Any]]:
    if not payload:
        raise ScreenshotCertificationError("gold sample is empty")
    if len(payload) > MAX_GOLD_BYTES:
        raise ScreenshotCertificationError(
            f"gold sample exceeds {MAX_GOLD_BYTES} byte limit"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScreenshotCertificationError("gold sample must be UTF-8") from exc

    suffix = Path(name).suffix.casefold()
    try:
        if suffix == ".jsonl":
            rows = []
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ScreenshotCertificationError(
                        f"gold JSONL line {line_number} is not an object"
                    )
                rows.append(value)
            return rows
        if suffix == ".json":
            value = json.loads(text)
            if not isinstance(value, list) or not all(
                isinstance(item, dict) for item in value
            ):
                raise ScreenshotCertificationError(
                    "gold JSON must be an array of objects"
                )
            return list(value)
    except json.JSONDecodeError as exc:
        raise ScreenshotCertificationError(f"invalid gold JSON: {exc}") from exc
    raise ScreenshotCertificationError("gold sample must be .json or .jsonl")


class ScreenshotCertification:
    def __init__(
        self,
        root: Path,
        *,
        work_root: Path | None = None,
        db_path: Path | None = None,
        corpus_root: Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.work_root = (
            Path(work_root).resolve()
            if work_root is not None
            else self.root / "inputs" / "screenshots" / "runtime" / "certification"
        )
        try:
            self.work_root.relative_to(self.root)
        except ValueError as exc:
            raise ScreenshotCertificationError(
                "certification work root must remain beneath the repository"
            ) from exc
        self.db_path = (
            Path(db_path).resolve()
            if db_path is not None
            else self.root / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
        )
        self.corpus_root = (
            Path(corpus_root).resolve()
            if corpus_root is not None
            else self.root / "data" / "FR24_baseline"
        )
        self.schema_path = self.root / "schemas" / "rlsm" / "gold_sample.v1.schema.json"
        self.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise ScreenshotCertificationError("RLSM database is unavailable")
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _sqlite_manifest(self) -> dict[str, Any]:
        if not self.db_path.is_file():
            raise ScreenshotCertificationError("RLSM database is unavailable")
        components = []
        aggregate = hashlib.sha256()
        for suffix in ("", "-wal"):
            path = Path(str(self.db_path) + suffix)
            if not path.is_file():
                continue
            item = {
                "component": "main" if not suffix else suffix.lstrip("-"),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            components.append(item)
            aggregate.update(_canonical_json(item).encode("utf-8"))
            aggregate.update(b"\n")
        return {
            "identity_class": "SOURCE_MANIFESTATION",
            "format": "sqlite_durable_manifestation_v1",
            "components": components,
            "excluded_transient_components": ["-shm"],
            "sha256": aggregate.hexdigest(),
        }

    def _corpus_manifest(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT screenshot_id,rel_path,sha256,size_bytes,ingest_status
                   FROM screenshots
                   ORDER BY screenshot_id"""
            ).fetchall()
        digest = hashlib.sha256()
        active = 0
        for row in rows:
            item = {
                "screenshot_id": int(row["screenshot_id"]),
                "rel_path": row["rel_path"],
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
                "ingest_status": row["ingest_status"],
            }
            if row["ingest_status"] == "ok":
                active += 1
            digest.update(_canonical_json(item).encode("utf-8"))
            digest.update(b"\n")
        return {
            "identity_class": "LOGICAL_MANIFEST",
            "basis": "ordered screenshots ledger: id,path,sha256,size,ingest_status",
            "rows": len(rows),
            "active_rows": active,
            "sha256": digest.hexdigest(),
        }

    def readiness(self) -> dict[str, Any]:
        db_exists = self.db_path.is_file()
        corpus_exists = self.corpus_root.is_dir()
        status: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tesseract_available": bool(shutil.which("tesseract")),
            "python_dependencies": {
                "Pillow": importlib.util.find_spec("PIL") is not None,
                "PyMuPDF": importlib.util.find_spec("fitz") is not None,
                "pytesseract": importlib.util.find_spec("pytesseract") is not None,
                "jsonschema": importlib.util.find_spec("jsonschema") is not None,
            },
            "rlsm_database_present": db_exists,
            "corpus_present": corpus_exists,
            "gold_schema_present": self.schema_path.is_file(),
            "certification_ready_for_audit": False,
            "operator_pipeline_ready": False,
            "latest_receipt": None,
        }
        schema_ready = False
        if db_exists:
            try:
                status["rlsm_database_manifest"] = self._sqlite_manifest()
                manifest = self._corpus_manifest()
                status["corpus_manifest"] = manifest
                status["active_screenshots"] = manifest["active_rows"]
                schema_ready = True
            except (sqlite3.DatabaseError, ScreenshotCertificationError) as exc:
                status["rlsm_database_error"] = f"{type(exc).__name__}: {exc}"
        status["rlsm_schema_ready"] = schema_ready
        if corpus_exists:
            status["corpus_path_state"] = "PRESENT_LOCAL"
        deps = status["python_dependencies"]
        status["operator_pipeline_ready"] = bool(
            status["tesseract_available"]
            and deps["Pillow"]
            and deps["pytesseract"]
            and schema_ready
            and corpus_exists
        )
        status["certification_ready_for_audit"] = bool(
            schema_ready and corpus_exists and status["gold_schema_present"]
        )
        receipts = self.list_receipts(limit=1)
        if receipts:
            status["latest_receipt"] = receipts[0]
        return status

    def _schema_validator(self) -> Draft202012Validator:
        if not self.schema_path.is_file():
            raise ScreenshotCertificationError("gold sample schema is unavailable")
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        return Draft202012Validator(schema)

    def validate_gold(
        self,
        name: str,
        payload: bytes,
        *,
        require_exact_denominator: bool = True,
    ) -> dict[str, Any]:
        rows = _parse_gold_bytes(name, payload)
        validator = self._schema_validator()
        schema_errors: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            for error in sorted(
                validator.iter_errors(row),
                key=lambda item: tuple(str(part) for part in item.path),
            ):
                schema_errors.append(
                    {
                        "index": index,
                        "path": list(error.path),
                        "message": error.message,
                    }
                )
        duplicate_raw_identities = 0
        seen_raw: set[tuple[str, str]] = set()
        for row in rows:
            identities = [
                ("screenshot_id", str(row["screenshot_id"]))
                if row.get("screenshot_id") is not None
                else None,
                ("screenshot_sha256", str(row["screenshot_sha256"]).casefold())
                if row.get("screenshot_sha256")
                else None,
                ("filename", str(row["filename"]))
                if row.get("filename")
                else None,
            ]
            identities = [item for item in identities if item is not None]
            if identities:
                canonical = identities[0]
                if canonical in seen_raw:
                    duplicate_raw_identities += 1
                seen_raw.add(canonical)

        unreviewed = 0
        non_independent = 0
        labels_not_explicit = 0
        for row in rows:
            if str(row.get("review_state") or "").casefold() != "reviewed":
                unreviewed += 1
            annotator = str(row.get("annotator") or "").strip()
            reviewer = str(row.get("reviewed_by") or "").strip()
            if (
                not annotator
                or not reviewer
                or annotator.casefold() == reviewer.casefold()
            ):
                non_independent += 1
            if "labels" not in row or not isinstance(row.get("labels"), list):
                labels_not_explicit += 1

        exact = len(rows) == EXPECTED_GOLD_RECORDS
        valid = (
            not schema_errors
            and duplicate_raw_identities == 0
            and unreviewed == 0
            and non_independent == 0
            and labels_not_explicit == 0
            and (exact or not require_exact_denominator)
        )
        return {
            "name": Path(name).name,
            "sha256": _sha256_bytes(payload),
            "records": len(rows),
            "expected_records": EXPECTED_GOLD_RECORDS,
            "exact_denominator": exact,
            "schema_errors": schema_errors,
            "duplicate_raw_identities": duplicate_raw_identities,
            "unreviewed_records": unreviewed,
            "non_independent_review_records": non_independent,
            "labels_not_explicit_records": labels_not_explicit,
            "valid_for_certification_attempt": valid,
        }

    def generate_gold_template(self, size: int = EXPECTED_GOLD_RECORDS) -> dict[str, Any]:
        if size != EXPECTED_GOLD_RECORDS:
            raise ScreenshotCertificationError(
                f"certification template size must be {EXPECTED_GOLD_RECORDS}"
            )
        with self._connect() as conn:
            frame_table = conn.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='frame_observations'"""
            ).fetchone()
            frame_expr = (
                """(SELECT f.frame_type FROM frame_observations f
                    WHERE f.screenshot_id=s.screenshot_id
                    ORDER BY f.frame_obs_id DESC LIMIT 1)"""
                if frame_table
                else "NULL"
            )
            rows = conn.execute(
                f"""SELECT s.screenshot_id,s.sha256,s.filename,s.month_bucket,
                           s.width,s.height,{frame_expr} AS frame_type
                    FROM screenshots s
                    WHERE s.ingest_status='ok'
                      AND COALESCE(s.source_availability,'present')='present'
                    ORDER BY s.screenshot_id"""
            ).fetchall()

        if len(rows) < size:
            raise ScreenshotCertificationError(
                f"active corpus has {len(rows)} screenshots; {size} are required"
            )

        strata: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            orientation = (
                "landscape"
                if row["width"] and row["height"] and row["width"] >= row["height"]
                else "portrait"
                if row["width"] and row["height"]
                else "unknown"
            )
            key = (
                str(row["frame_type"] or "unknown"),
                orientation,
                str(row["month_bucket"] or "unknown"),
            )
            strata[key].append(row)

        selected: list[tuple[tuple[str, str, str], sqlite3.Row]] = []
        cursors = {key: 0 for key in strata}
        keys = sorted(strata)
        while len(selected) < size:
            advanced = False
            for key in keys:
                cursor = cursors[key]
                bucket = strata[key]
                if cursor >= len(bucket):
                    continue
                selected.append((key, bucket[cursor]))
                cursors[key] += 1
                advanced = True
                if len(selected) == size:
                    break
            if not advanced:
                break

        if len(selected) != size:
            raise ScreenshotCertificationError("could not close 300-frame selection denominator")

        records = []
        selected_strata: dict[str, int] = defaultdict(int)
        for key, row in selected:
            selected_strata["|".join(key)] += 1
            records.append(
                {
                    "screenshot_id": int(row["screenshot_id"]),
                    "screenshot_sha256": str(row["sha256"]),
                    "filename": str(row["filename"]),
                    "labels": [],
                    "annotator": "",
                    "reviewed_by": "",
                    "review_state": "unreviewed",
                    "notes": "UNREVIEWED_TEMPLATE: annotate labels including [] for reviewed absence.",
                }
            )

        data = "".join(_canonical_json(record) + "\n" for record in records).encode("utf-8")
        selection_manifest = {
            "selection_method": "deterministic_stratum_round_robin_v1",
            "source_active_rows": len(rows),
            "selected_rows": len(records),
            "strata_in_source": len(strata),
            "strata_in_sample": len(selected_strata),
            "selected_strata_counts": dict(sorted(selected_strata.items())),
            "corpus_manifest": self._corpus_manifest(),
        }
        return {
            "name": "gold_sample_300.template.jsonl",
            "sha256": _sha256_bytes(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
            "selection_manifest": selection_manifest,
        }

    def run_audit(self, name: str, payload: bytes) -> dict[str, Any]:
        validation = self.validate_gold(name, payload)
        if validation["schema_errors"]:
            raise ScreenshotCertificationError(
                "gold sample does not satisfy schemas/rlsm/gold_sample.v1.schema.json"
            )
        readiness = self.readiness()
        if not readiness["certification_ready_for_audit"]:
            raise ScreenshotCertificationError(
                "local RLSM database, corpus, and gold schema are required"
            )

        db_before = self._sqlite_manifest()
        corpus_before = self._corpus_manifest()
        fingerprint_input = {
            "schema_version": SCHEMA_VERSION,
            "gold_sha256": validation["sha256"],
            "rlsm_database_manifest_sha256": db_before["sha256"],
            "corpus_manifest_sha256": corpus_before["sha256"],
        }
        fingerprint = _sha256_bytes(_canonical_json(fingerprint_input).encode("utf-8"))
        run_id = fingerprint[:24]
        run_dir = self.work_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_path = run_dir / "receipt.json"
        if receipt_path.is_file():
            return json.loads(receipt_path.read_text(encoding="utf-8"))

        suffix = Path(name).suffix.casefold()
        gold_path = run_dir / f"gold_sample{suffix}"
        gold_path.write_bytes(payload)
        outputs_dir = run_dir / "outputs"
        try:
            with _AUDIT_LOCK:
                report = audit_v2.run(
                    db_path=self.db_path,
                    corpus_root=self.corpus_root,
                    gold_path=gold_path,
                    outputs_dir=outputs_dir,
                    sample_limit=25,
                )
        except (FileNotFoundError, sqlite3.DatabaseError, ValueError) as exc:
            raise ScreenshotCertificationError(
                f"certification audit failed: {type(exc).__name__}: {exc}"
            ) from exc

        db_after = self._sqlite_manifest()
        corpus_after = self._corpus_manifest()
        stable = (
            db_before["sha256"] == db_after["sha256"]
            and corpus_before["sha256"] == corpus_after["sha256"]
        )
        output_hashes: dict[str, str] = {}
        for path in sorted(outputs_dir.rglob("*")):
            if path.is_file():
                output_hashes[path.relative_to(run_dir).as_posix()] = _sha256_file(path)

        audit_status = str(report["certification_status"])
        receipt_status = audit_status if stable else "UNRESOLVED"
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": _utc_now(),
            "certification_status": receipt_status,
            "audit_certification_status": audit_status,
            "gold_validation": validation,
            "inputs": {
                "gold_sample_name": Path(name).name,
                "gold_sample_sha256": validation["sha256"],
                "rlsm_database_manifest_before": db_before,
                "rlsm_database_manifest_after": db_after,
                "corpus_manifest_before": corpus_before,
                "corpus_manifest_after": corpus_after,
                "inputs_stable_during_audit": stable,
            },
            "gold_sample": report["gold_sample"],
            "required_gates": report["required_gates"],
            "gates": report["gates"],
            "error_count": report["error_count"],
            "output_hashes": output_hashes,
            "canonical_mfl_mutation_authorized": False,
        }
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return receipt

    def list_receipts(self, limit: int = 20) -> list[dict[str, Any]]:
        receipts = []
        for path in sorted(
            self.work_root.glob("*/receipt.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                receipts.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if len(receipts) >= max(1, min(int(limit), 100)):
                break
        return receipts


__all__ = [
    "EXPECTED_GOLD_RECORDS",
    "MAX_GOLD_BYTES",
    "ScreenshotCertification",
    "ScreenshotCertificationError",
]
