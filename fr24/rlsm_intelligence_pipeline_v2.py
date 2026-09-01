"""Certified stage policy layered over the screenshot-intelligence pipeline."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from fr24 import rlsm_intelligence_pipeline as pipeline

REPO = pipeline.REPO
DB = pipeline.DB
BASELINE = pipeline.BASELINE
_BASE_COLLECT_STATUS = pipeline.collect_status


@dataclass
class RefreshState:
    requested: bool = False
    done: bool = False


_REFRESH_STATE = RefreshState()


def defer_refresh() -> dict[str, int]:
    """Record the request; destructive refresh runs only after preflight passes."""
    _REFRESH_STATE.requested = True
    return {"deferred_until_after_preflight": 1}


def stage_preflight(ctx: dict) -> None:
    pipeline.stage_preflight(ctx)
    has_mutating_stage = any(stage != "preflight" for stage in ctx.get("stages", []))
    should_refresh = (
        _REFRESH_STATE.requested
        and has_mutating_stage
        and not ctx.get("dry_run", False)
        and not _REFRESH_STATE.done
    )
    if should_refresh:
        deleted = refresh_derived()
        _REFRESH_STATE.done = True
        print(
            f"    · refreshed derived rows after preflight: {json.dumps(deleted, sort_keys=True)}",
            flush=True,
        )


def stage_inventory(ctx: dict) -> None:
    pipeline.stage_inventory(ctx)
    pipeline.base._run_module(
        "fr24.rlsm_source_reconcile",
        [
            "--db",
            str(DB),
            "--repo-root",
            str(REPO),
            "--corpus-root",
            str(BASELINE),
            "--output",
            str(REPO / "outputs" / "rlsm_source_reconciliation.json"),
        ],
    )


def stage_ocr(ctx: dict) -> None:
    args = [
        "--workers",
        str(ctx["workers"]),
        "--budget-sec",
        str(ctx["budget_sec"]),
        "--db",
        str(DB),
        "--repo-root",
        str(REPO),
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


def stage_aircraft(ctx: dict) -> None:
    args = [
        "--kind",
        "aircraft",
        "--db",
        str(DB),
        "--repo-root",
        str(REPO),
    ]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_extractors_certified", args)


def stage_pins(ctx: dict) -> None:
    args = [
        "--kind",
        "labeled_poi",
        "--db",
        str(DB),
        "--repo-root",
        str(REPO),
    ]
    partial_args = ["--db", str(DB)]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
        partial_args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_extractors_certified", args)
    pipeline.base._run_module("fr24.rlsm_partial_extract", partial_args)


def stage_icons(ctx: dict) -> None:
    args = [
        "--db",
        str(DB),
        "--repo-root",
        str(REPO),
        "--budget-sec",
        str(ctx["budget_sec"]),
        "--naming-file",
        str(REPO / "outputs" / "icon_classes.generated.json"),
    ]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_icons_certified", args)


def stage_tracks(ctx: dict) -> None:
    args = [
        "--budget-sec",
        str(ctx["budget_sec"]),
        "--image-root",
        str(BASELINE),
        "--db",
        str(DB),
    ]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_flight_track_certified", args)


def stage_frames(ctx: dict) -> None:
    args = ["--db", str(DB)]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    pipeline.base._run_module("fr24.rlsm_frame_artifacts", args)


def stage_icon_crops(ctx: dict) -> None:
    args = [
        "--db",
        str(DB),
        "--image-root",
        str(BASELINE),
        "--output-root",
        str(REPO / "outputs" / "icon_library"),
        "--manifest",
        str(REPO / "outputs" / "icon_library_manifest.jsonl"),
    ]
    # A pipeline limit scopes screenshots in upstream extraction stages. At this
    # point every persisted icon belongs to that bounded screenshot set, so all
    # current icon rows must be materialized; limiting icon rows would create a
    # false artifact-accounting failure.
    pipeline.base._run_script(REPO / "scripts" / "rlsm_capture_icon_crops.py", args)


def stage_provenance(ctx: dict) -> None:
    pipeline.base._run_module("fr24.rlsm_provenance", ["--db", str(DB)])


def stage_review(ctx: dict) -> None:
    pipeline.base._run_module(
        "fr24.rlsm_extractors_certified",
        [
            "--kind",
            "review_queue",
            "--db",
            str(DB),
            "--repo-root",
            str(REPO),
        ],
    )


def stage_export(ctx: dict) -> None:
    pipeline.stage_export(ctx)
    pipeline.base._run_module(
        "fr24.rlsm_intelligence_export",
        [
            "--db",
            str(DB),
            "--output-dir",
            str(REPO / "outputs" / "screenshot_intelligence"),
        ],
    )


def stage_audit(ctx: dict) -> None:
    args = [
        "--db",
        str(DB),
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
    status = _BASE_COLLECT_STATUS()
    status["repo_resolved"] = str(REPO.resolve())
    status["db_resolved"] = str(DB.resolve())
    status["corpus_resolved"] = str(BASELINE.resolve()) if BASELINE.exists() else None
    if not DB.exists() or not status.get("schema"):
        return status
    conn = sqlite3.connect(str(DB), timeout=30.0)
    status["ingest_status"] = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT ingest_status, COUNT(*) FROM screenshots GROUP BY ingest_status"
        )
    }
    for key, table in (
        ("track_extraction_receipts", "track_extraction_receipts"),
        ("icon_scan_receipts", "icon_scan_receipts"),
        ("source_reconciliation_receipts", "source_reconciliation_receipts"),
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
        status["icon_scan_truncations"] = pipeline.base._count(
            conn,
            "SELECT COUNT(*) FROM icon_scan_receipts WHERE scan_status='truncated'",
        )
    conn.close()
    return status


def install_policy() -> None:
    pipeline.STAGE_FUNCS["preflight"] = stage_preflight
    pipeline.STAGE_FUNCS["inventory"] = stage_inventory
    pipeline.STAGE_FUNCS["ocr"] = stage_ocr
    pipeline.STAGE_FUNCS["aircraft"] = stage_aircraft
    pipeline.STAGE_FUNCS["pins"] = stage_pins
    pipeline.STAGE_FUNCS["icons"] = stage_icons
    pipeline.STAGE_FUNCS["tracks"] = stage_tracks
    pipeline.STAGE_FUNCS["frames"] = stage_frames
    pipeline.STAGE_FUNCS["icon_crops"] = stage_icon_crops
    pipeline.STAGE_FUNCS["provenance"] = stage_provenance
    pipeline.STAGE_FUNCS["review"] = stage_review
    pipeline.STAGE_FUNCS["export"] = stage_export
    pipeline.STAGE_FUNCS["audit"] = stage_audit
    pipeline._refresh_derived = defer_refresh
    pipeline.collect_status = collect_status


def main(argv: list[str] | None = None) -> int:
    _REFRESH_STATE.requested = False
    _REFRESH_STATE.done = False
    install_policy()
    result = pipeline.main(argv)
    if result != 0:
        print(
            json.dumps(
                {
                    "pipeline": "screenshot_intelligence_v2",
                    "status": "failed",
                    "exit_code": result,
                    "database": str(DB.resolve()),
                    "repo_root": str(REPO.resolve()),
                },
                sort_keys=True,
            )
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
