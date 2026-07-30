"""Certified stage policy layered over the screenshot-intelligence pipeline."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fr24 import rlsm_intelligence_pipeline as pipeline

REPO = pipeline.REPO
DB = pipeline.DB
BASELINE = pipeline.BASELINE


def stage_ocr(ctx: dict) -> None:
    args = [
        "--workers",
        str(ctx["workers"]),
        "--budget-sec",
        str(ctx["budget_sec"]),
    ]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    if ctx["retry_failed_ocr"]:
        args.append("--retry-failed")
    pipeline.base._run_module("fr24.rlsm_ocr_certified", args)
    if ctx.get("preflight", {}).get("screenshots_needing_word_boxes"):
        pipeline.base._run_module(
            "fr24.rlsm_ocr_certified",
            args + ["--reocr-boxes"],
        )


def stage_tracks(ctx: dict) -> None:
    args = [
        "--budget-sec",
        str(ctx["budget_sec"]),
        "--image-root",
        str(REPO),
    ]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_flight_track_certified", args)


def stage_export(ctx: dict) -> None:
    pipeline.stage_export(ctx)
    pipeline.base._run_module("fr24.rlsm_intelligence_export", [])


def stage_audit(ctx: dict) -> None:
    args = [
        "--corpus-root",
        str(BASELINE),
        "--gold",
        str(ctx["gold_sample"]),
    ]
    if ctx["limit"]:
        args += ["--sample-limit", str(min(ctx["limit"], 25))]
    if ctx["certify"]:
        args.append("--enforce")
    pipeline.base._run_module("fr24.rlsm_intelligence_audit_v2", args)


def refresh_derived() -> dict[str, int]:
    if not DB.exists():
        return {}
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = OFF")
    tables = (
        "extraction_field_provenance",
        "icon_artifacts",
        "icon_scan_receipts",
        "track_extraction_receipts",
        "icon_observations",
        "flight_track_features",
        "aircraft_observations",
        "labeled_pins",
        "map_state_observations",
        "gui_artifact_observations",
        "frame_observations",
    )
    deleted: dict[str, int] = {}
    with conn:
        for table in tables:
            if pipeline.base._table_exists(conn, table):
                before = pipeline.base._count(conn, f"SELECT COUNT(*) FROM {table}")
                conn.execute(f"DELETE FROM {table}")
                deleted[table] = before
    conn.close()
    return deleted


def collect_status() -> dict:
    status = pipeline.collect_status()
    if not DB.exists() or not status.get("schema"):
        return status
    conn = sqlite3.connect(str(DB), timeout=30.0)
    for key, table in (
        ("track_extraction_receipts", "track_extraction_receipts"),
        ("icon_scan_receipts", "icon_scan_receipts"),
    ):
        if pipeline.base._table_exists(conn, table):
            status[key] = pipeline.base._count(conn, f"SELECT COUNT(*) FROM {table}")
    if pipeline.base._table_exists(conn, "track_extraction_receipts"):
        status["track_extraction_failures"] = pipeline.base._count(
            conn,
            "SELECT COUNT(*) FROM track_extraction_receipts WHERE cv_status='failed'",
        )
    if pipeline.base._table_exists(conn, "icon_scan_receipts"):
        status["icon_scan_failures"] = pipeline.base._count(
            conn,
            "SELECT COUNT(*) FROM icon_scan_receipts WHERE scan_status='failed'",
        )
    conn.close()
    return status


def install_policy() -> None:
    pipeline.STAGE_FUNCS["ocr"] = stage_ocr
    pipeline.STAGE_FUNCS["tracks"] = stage_tracks
    pipeline.STAGE_FUNCS["export"] = stage_export
    pipeline.STAGE_FUNCS["audit"] = stage_audit
    pipeline._refresh_derived = refresh_derived
    pipeline.collect_status = collect_status


def main(argv: list[str] | None = None) -> int:
    install_policy()
    result = pipeline.main(argv)
    if result != 0:
        print(
            json.dumps(
                {
                    "pipeline": "screenshot_intelligence_v2",
                    "status": "failed",
                    "exit_code": result,
                },
                sort_keys=True,
            )
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
