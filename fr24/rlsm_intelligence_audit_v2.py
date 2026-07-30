"""Version-2 certification policy for Skywatcher screenshot intelligence."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from fr24 import rlsm_intelligence_audit as audit

DB = audit.DB
CORPUS = audit.CORPUS
GOLD = audit.GOLD
_BASE_AUDIT_OCR_INTEGRITY = audit.audit_ocr_integrity
_BASE_AUDIT_CAPABILITIES = audit.audit_capabilities
_BASE_BUILD_GATES = audit.build_gates

REQUIRED_GATES = (
    "screenshot_accounting_100",
    "no_silent_failures",
    "frame_accounting_100",
    "gui_artifact_frame_coverage_100",
    "track_extraction_accounting_100",
    "icon_scan_accounting_100",
    "icon_capture_complete",
    "no_unsupported_geolocation",
    "field_level_provenance_100",
    "location_label_recall_gte_0_98",
)


def _optional_count(conn: sqlite3.Connection, table: str, where: str = "") -> int:
    if not audit._table_exists(conn, table):
        return 0
    return audit._count(conn, f"SELECT COUNT(*) FROM {table} {where}")


def audit_ocr_integrity(
    conn: sqlite3.Connection,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result, errors = _BASE_AUDIT_OCR_INTEGRITY(conn)
    in_progress = int(result.get("runs_left_in_progress", 0))
    result["silent_failure_count"] = int(result.get("silent_failure_count", 0)) + in_progress
    result["complete"] = result["silent_failure_count"] == 0
    result["policy"] = "in_progress_runs_are_failures_v2"
    return result, errors


def audit_capabilities(conn: sqlite3.Connection) -> dict[str, Any]:
    capabilities = _BASE_AUDIT_CAPABILITIES(conn)
    ingest_ok = int(capabilities["ingestion"]["screenshots"])

    track_receipts = _optional_count(conn, "track_extraction_receipts")
    track_failures = _optional_count(
        conn,
        "track_extraction_receipts",
        "WHERE cv_status='failed'",
    )
    track_ok = _optional_count(
        conn,
        "track_extraction_receipts",
        "WHERE cv_status IN ('ok','no_track_detected')",
    )
    capabilities["track_extraction_receipts"] = {
        "status": "complete" if track_receipts == ingest_ok and track_failures == 0 else "incomplete",
        "rows": track_receipts,
        "valid_negative_or_positive": track_ok,
        "failures": track_failures,
        "coverage_percent": audit._pct(track_receipts, ingest_ok),
    }

    icon_receipts = _optional_count(conn, "icon_scan_receipts")
    icon_scan_failures = _optional_count(
        conn,
        "icon_scan_receipts",
        "WHERE scan_status='failed'",
    )
    capabilities["standalone_icon_scan"] = {
        "status": "complete" if icon_receipts == ingest_ok and icon_scan_failures == 0 else "incomplete",
        "rows": icon_receipts,
        "failures": icon_scan_failures,
        "coverage_percent": audit._pct(icon_receipts, ingest_ok),
    }

    gui_frames = 0
    gui_failed_rows = 0
    if audit._table_exists(conn, "gui_artifact_observations"):
        gui_frames = audit._count(
            conn,
            "SELECT COUNT(DISTINCT screenshot_id) FROM gui_artifact_observations",
        )
        gui_failed_rows = audit._count(
            conn,
            "SELECT COUNT(*) FROM gui_artifact_observations WHERE extraction_status='failed'",
        )
    capabilities["gui_artifacts"]["screenshot_frames"] = gui_frames
    capabilities["gui_artifacts"]["failed_rows"] = gui_failed_rows
    capabilities["gui_artifacts"]["frame_coverage_percent"] = audit._pct(
        gui_frames,
        ingest_ok,
    )
    return capabilities


def build_gates(
    accounting: dict[str, Any],
    ocr: dict[str, Any],
    capabilities: dict[str, Any],
    geolocation: dict[str, Any],
    provenance: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    gates = _BASE_BUILD_GATES(
        accounting,
        ocr,
        capabilities,
        geolocation,
        provenance,
        gold,
    )
    ingest_ok = int(capabilities["ingestion"]["screenshots"])

    gui = capabilities["gui_artifacts"]
    gui_complete = gui.get("screenshot_frames", 0) == ingest_ok
    gates["gui_artifact_frame_coverage_100"] = audit._gate(
        "PASS" if gui_complete else "FAIL",
        {
            "frames": gui.get("screenshot_frames", 0),
            "ingest_ok": ingest_ok,
            "failed_rows": gui.get("failed_rows", 0),
        },
    )

    tracks = capabilities["track_extraction_receipts"]
    track_complete = tracks["rows"] == ingest_ok and tracks["failures"] == 0
    gates["track_extraction_accounting_100"] = audit._gate(
        "PASS" if track_complete else "FAIL",
        {
            "receipts": tracks["rows"],
            "ingest_ok": ingest_ok,
            "failures": tracks["failures"],
        },
    )

    icon_scan = capabilities["standalone_icon_scan"]
    scan_complete = icon_scan["rows"] == ingest_ok and icon_scan["failures"] == 0
    gates["icon_scan_accounting_100"] = audit._gate(
        "PASS" if scan_complete else "FAIL",
        {
            "receipts": icon_scan["rows"],
            "ingest_ok": ingest_ok,
            "failures": icon_scan["failures"],
        },
    )

    icons = capabilities["icons"]
    icon_complete = (
        scan_complete
        and icons["detected"] > 0
        and icons["detected"] == icons["artifacts"]
        and icons["artifact_failures"] == 0
    )
    gates["icon_capture_complete"] = audit._gate(
        "PASS" if icon_complete else "FAIL",
        {
            "scan_receipts": icon_scan["rows"],
            "detected": icons["detected"],
            "artifacts": icons["artifacts"],
            "artifact_failures": icons["artifact_failures"],
        },
    )
    return gates


def _certification_status(gates: dict[str, dict[str, Any]]) -> str:
    statuses = [gates[name]["status"] for name in REQUIRED_GATES]
    if all(status == "PASS" for status in statuses):
        return "PASS"
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    return "BLOCKED"


def run(
    *,
    db_path: Path = DB,
    corpus_root: Path = CORPUS,
    gold_path: Path = GOLD,
    outputs_dir: Path | None = None,
    sample_limit: int = 25,
) -> dict[str, Any]:
    audit.audit_ocr_integrity = audit_ocr_integrity
    audit.audit_capabilities = audit_capabilities
    audit.build_gates = build_gates
    audit.REQUIRED_GATES = REQUIRED_GATES

    report = audit.run(
        db_path=db_path,
        corpus_root=corpus_root,
        gold_path=gold_path,
        outputs_dir=outputs_dir,
        sample_limit=sample_limit,
    )
    report["schema_version"] = "skywatcher_screenshot_intelligence_audit.v2"
    report["certification_status"] = _certification_status(report["gates"])
    report["required_gates"] = list(REQUIRED_GATES)

    json_path = Path(report["outputs"]["json"])
    markdown_path = Path(report["outputs"]["markdown"])
    capability_path = Path(report["outputs"]["capabilities"])
    audit._write_json(json_path, report)
    audit._write_json(capability_path, report["capabilities"])
    markdown_path.write_text(audit._markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS)
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--outputs-dir", type=Path, default=None)
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(
            db_path=args.db,
            corpus_root=args.corpus_root,
            gold_path=args.gold,
            outputs_dir=args.outputs_dir,
            sample_limit=args.sample_limit,
        )
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "certification_status": report["certification_status"],
                "gates": report["gates"],
                "error_count": report["error_count"],
                "outputs": report["outputs"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if args.enforce and report["certification_status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
