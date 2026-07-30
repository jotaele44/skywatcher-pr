"""End-to-end RLSM screenshot-intelligence pipeline and certification entry point."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24 import rlsm_pipeline as base  # noqa: E402

DB = base.DB
BASELINE = base.BASELINE
GOLD = REPO / "data" / "rlsm" / "gold_sample_300.jsonl"

ALL_STAGES = [
    "preflight", "inventory", "ocr", "aircraft", "pins", "icons",
    "tracks", "frames", "icon_crops", "geocode", "provenance",
    "review", "export", "audit", "report",
]
OPTIONAL_STAGES = ["unlabeled"]
DEFAULT_STAGES = list(ALL_STAGES)


def stage_preflight(ctx: dict) -> None:
    preflight_ctx = dict(ctx)
    pixel_stages = {"inventory", "ocr", "icons", "tracks", "icon_crops", "unlabeled"}
    stages = list(ctx["stages"])
    if pixel_stages & set(stages) and not {"inventory", "ocr", "icons", "unlabeled"} & set(stages):
        stages.append("icons")
    preflight_ctx["stages"] = stages
    info = base.preflight(preflight_ctx)
    ctx["preflight"] = info


def stage_inventory(ctx: dict) -> None:
    base.stage_inventory(ctx)


def stage_ocr(ctx: dict) -> None:
    common = ["--workers", str(ctx["workers"]), "--budget-sec", str(ctx["budget_sec"])]
    if ctx["limit"]:
        common += ["--limit", str(ctx["limit"])]
    if ctx["retry_failed_ocr"]:
        common.append("--retry-failed")
    base._run_module("fr24.rlsm_ocr_strict", common)
    if ctx.get("preflight", {}).get("screenshots_needing_word_boxes"):
        base._run_module("fr24.rlsm_ocr_strict", common + ["--reocr-boxes"])


def stage_aircraft(ctx: dict) -> None:
    base.stage_aircraft(ctx)


def stage_pins(ctx: dict) -> None:
    args = ["--kind", "labeled_poi"]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    base._run_module("fr24.rlsm_extractors", args)
    partial_args: list[str] = []
    if ctx["limit"]:
        partial_args += ["--limit", str(ctx["limit"])]
    base._run_module("fr24.rlsm_partial_extract", partial_args)


def stage_icons(ctx: dict) -> None:
    base.stage_icons(ctx)


def _delete_upgradeable_tracks() -> int:
    if not DB.exists():
        return 0
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    cursor = conn.execute(
        """DELETE FROM flight_track_features
           WHERE (bbox_x IS NULL OR bbox_y IS NULL OR bbox_w IS NULL OR bbox_h IS NULL)
             AND COALESCE(confidence, 0) <= 0.3"""
    )
    deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
    conn.commit()
    conn.close()
    return deleted


def stage_tracks(ctx: dict) -> None:
    if ctx["upgrade_tracks"]:
        deleted = _delete_upgradeable_tracks()
        print(f"    · removed {deleted} heuristic-only track rows for CV upgrade", flush=True)
    args = ["--budget-sec", str(ctx["budget_sec"]), "--image-root", str(REPO)]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    base._run_module("fr24.rlsm_flight_track", args)


def stage_frames(ctx: dict) -> None:
    args: list[str] = []
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    base._run_module("fr24.rlsm_frame_artifacts", args)


def stage_icon_crops(ctx: dict) -> None:
    args = ["--image-root", str(BASELINE)]
    if ctx["limit"]:
        args += ["--limit", str(ctx["limit"])]
    base._run_script(REPO / "scripts" / "rlsm_capture_icon_crops.py", args)


def stage_geocode(ctx: dict) -> None:
    base.stage_geocode(ctx)


def stage_provenance(ctx: dict) -> None:
    base._run_module("fr24.rlsm_provenance", [])


def stage_review(ctx: dict) -> None:
    base.stage_review(ctx)


def stage_export(ctx: dict) -> None:
    base.stage_export(ctx)


def stage_audit(ctx: dict) -> None:
    args = ["--corpus-root", str(BASELINE), "--gold", str(ctx["gold_sample"])]
    if ctx["limit"]:
        args += ["--sample-limit", str(min(ctx["limit"], 25))]
    if ctx["certify"]:
        args.append("--enforce")
    base._run_module("fr24.rlsm_intelligence_audit", args)


def stage_report(ctx: dict) -> None:
    base.stage_report(ctx)


def stage_unlabeled(ctx: dict) -> None:
    base.stage_unlabeled(ctx)


STAGE_FUNCS: dict[str, Callable[[dict], None]] = {
    "preflight": stage_preflight,
    "inventory": stage_inventory,
    "ocr": stage_ocr,
    "aircraft": stage_aircraft,
    "pins": stage_pins,
    "icons": stage_icons,
    "tracks": stage_tracks,
    "frames": stage_frames,
    "icon_crops": stage_icon_crops,
    "geocode": stage_geocode,
    "provenance": stage_provenance,
    "review": stage_review,
    "export": stage_export,
    "audit": stage_audit,
    "report": stage_report,
    "unlabeled": stage_unlabeled,
}


def resolve_stages(args: argparse.Namespace) -> list[str]:
    if args.stage:
        if args.stage not in STAGE_FUNCS:
            raise SystemExit(f"unknown stage {args.stage!r}; choose from {', '.join(STAGE_FUNCS)}")
        return [args.stage] if args.stage == "preflight" else ["preflight", args.stage]
    stages = list(DEFAULT_STAGES)
    if args.from_stage:
        if args.from_stage not in stages:
            raise SystemExit(f"unknown stage {args.from_stage!r}; choose from {', '.join(stages)}")
        stages = ["preflight"] + stages[stages.index(args.from_stage):]
        stages = list(dict.fromkeys(stages))
    if args.skip_icons:
        stages = [stage for stage in stages if stage not in {"icons", "icon_crops"}]
    if args.skip_tracks:
        stages = [stage for stage in stages if stage != "tracks"]
    return stages


def collect_status() -> dict:
    status = base.collect_status()
    if not DB.exists() or not status.get("schema"):
        return status
    conn = sqlite3.connect(str(DB), timeout=30.0)
    for key, table in (
        ("flight_track_features", "flight_track_features"),
        ("frame_observations", "frame_observations"),
        ("map_state_observations", "map_state_observations"),
        ("gui_artifact_observations", "gui_artifact_observations"),
        ("icon_artifacts", "icon_artifacts"),
        ("field_provenance", "extraction_field_provenance"),
    ):
        if base._table_exists(conn, table):
            status[key] = base._count(conn, f"SELECT COUNT(*) FROM {table}")
    if base._table_exists(conn, "flight_track_features"):
        status["pixel_derived_tracks"] = base._count(conn, "SELECT COUNT(*) FROM flight_track_features WHERE bbox_x IS NOT NULL AND confidence>=0.6")
    if base._table_exists(conn, "icon_artifacts"):
        status["icon_capture_failures"] = base._count(conn, "SELECT COUNT(*) FROM icon_artifacts WHERE capture_status!='ok'")
    conn.close()
    audit_path = REPO / "outputs" / "screenshot_intelligence_audit.json"
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            status["screenshot_intelligence_certification"] = audit.get("certification_status")
            status["screenshot_intelligence_gates"] = audit.get("gates")
        except (OSError, ValueError, TypeError):
            status["screenshot_intelligence_certification"] = "unreadable_report"
    return status


def _refresh_derived() -> dict[str, int]:
    if not DB.exists():
        return {}
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = OFF")
    tables = (
        "extraction_field_provenance", "icon_artifacts", "icon_observations",
        "flight_track_features", "aircraft_observations", "labeled_pins",
        "frame_observations", "map_state_observations", "gui_artifact_observations",
    )
    deleted: dict[str, int] = {}
    with conn:
        for table in tables:
            if base._table_exists(conn, table):
                before = base._count(conn, f"SELECT COUNT(*) FROM {table}")
                conn.execute(f"DELETE FROM {table}")
                deleted[table] = before
    conn.close()
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run-rlsm.sh",
        description="Run and certify the Skywatcher screenshot-intelligence pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Stages: " + ", ".join(ALL_STAGES) + "\nOptional: " + ", ".join(OPTIONAL_STAGES),
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stage", choices=list(STAGE_FUNCS), default=None)
    parser.add_argument("--from", dest="from_stage", choices=ALL_STAGES, default=None)
    parser.add_argument("--skip-icons", action="store_true")
    parser.add_argument("--skip-tracks", action="store_true")
    parser.add_argument("--retry-failed-ocr", action="store_true")
    parser.add_argument("--no-upgrade-tracks", dest="upgrade_tracks", action="store_false")
    parser.set_defaults(upgrade_tracks=True)
    parser.add_argument("--refresh-derived", action="store_true")
    parser.add_argument("--gold-sample", type=Path, default=GOLD)
    parser.add_argument("--certify", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(collect_status(), indent=2, sort_keys=True))
        return 0
    stages = resolve_stages(args)
    ctx = {
        "workers": max(1, args.workers), "budget_sec": max(1.0, args.budget_sec),
        "limit": max(0, args.limit), "stages": stages, "dry_run": args.dry_run,
        "skip_icons": args.skip_icons, "retry_failed_ocr": args.retry_failed_ocr,
        "upgrade_tracks": args.upgrade_tracks, "gold_sample": args.gold_sample,
        "certify": args.certify, "preflight": {},
    }
    print("RLSM screenshot-intelligence pipeline", flush=True)
    print(f"  stages: {' → '.join(stages)}", flush=True)
    print(f"  certify: {args.certify}", flush=True)
    print(f"  gold: {args.gold_sample}", flush=True)
    if args.dry_run:
        stage_preflight(dict(ctx))
        print("  dry-run: no stage mutations executed", flush=True)
        return 0
    if args.refresh_derived:
        deleted = _refresh_derived()
        print(f"  refreshed derived rows: {json.dumps(deleted, sort_keys=True)}", flush=True)
    for stage in stages:
        print(f"\n[{stage}]", flush=True)
        try:
            STAGE_FUNCS[stage](ctx)
        except (base.StageError, sqlite3.DatabaseError, OSError) as exc:
            print(f"  ✗ {stage}: {exc}", file=sys.stderr, flush=True)
            return 1
        print(f"  ✓ {stage}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
