"""
GEO-PR-INT — Geospatial Puerto Rico Intelligence System

CLI entry point.

Usage
-----
  python main.py --run                    # full pipeline run
  python main.py --incremental            # incremental refresh
  python main.py --serve                  # start FastAPI server
  python main.py --run --live             # re-fetch satellite data live
  python main.py --run --force-api        # bypass local contract CSV
  python main.py --run --log-level DEBUG  # verbose logging
"""

import argparse
import sys
from pathlib import Path

# Make the package importable whether called as `python main.py` from the
# geo_pr_int/ directory or as `python geo_pr_int/main.py` from the repo root.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="geo_pr_int",
        description="GEO-PR-INT: Geospatial Puerto Rico Intelligence System",
    )

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run",         action="store_true", help="Run full pipeline")
    mode.add_argument("--incremental", action="store_true", help="Incremental refresh")
    mode.add_argument("--serve",       action="store_true", help="Start FastAPI server")

    p.add_argument("--live",      action="store_true",
                   help="Re-fetch satellite data live (slower)")
    p.add_argument("--force-api", action="store_true",
                   help="Query USASpending API directly, skip local CSV")
    p.add_argument(
        "--aoi", nargs=4, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        type=float, default=None,
        help="Override area of interest bounding box",
    )
    p.add_argument("--since", default=None,
                   help="Incremental: only process data after this ISO date")
    p.add_argument("--host", default="0.0.0.0", help="API server host (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="API server port (default 8000)")
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return p.parse_args(argv)


def _print_summary(result) -> None:
    """Print a formatted summary table to stdout."""
    s = result.summary
    print("\n" + "=" * 55)
    print("  GEO-PR-INT Pipeline Summary")
    print("=" * 55)
    print(f"  Run timestamp   : {result.run_timestamp}")
    print(f"  Total candidates: {s.get('total_candidates', len(result.candidates_df))}")
    print(f"  Corridors found : {s.get('total_corridors', len(result.corridors_df))}")
    print(f"  Contracts loaded: {s.get('total_contracts', len(result.contracts_df))}")
    print(f"  CRITICAL alerts : {s.get('critical_count', 0)}")
    print(f"  HIGH alerts     : {s.get('high_count', 0)}")
    print(f"  Mean score      : {s.get('mean_score', 0):.1f} / 100")
    print(f"  Pipeline time   : {s.get('total_seconds', 0):.1f}s")
    if result.errors:
        print(f"  Warnings/errors : {len(result.errors)}")
        for e in result.errors[:5]:
            print(f"    • {e}")
    print("=" * 55)

    top5 = s.get("top_5", [])
    if top5:
        print("\n  Top candidates:")
        for i, loc in enumerate(top5, 1):
            print(
                f"  {i}. ({loc['lat']:.4f}, {loc['lon']:.4f}) "
                f"score={loc['unified_score']:.1f} "
                f"type={loc.get('infra_type','?')} "
                f"corridor={loc.get('corridor_id', 0)}"
            )
    print()


def main(argv=None) -> int:
    args = _parse_args(argv)

    from utils.logging import configure_logging
    configure_logging(level=args.log_level)

    aoi = tuple(args.aoi) if args.aoi else None

    # ── Full run ───────────────────────────────────────────────────────────────
    if args.run:
        from pipeline.full_run import run_full_pipeline
        result = run_full_pipeline(
            aoi=aoi,
            live_satellite=args.live,
            force_api=args.force_api,
        )
        _print_summary(result)
        return 0 if not result.errors else 1

    # ── Incremental ────────────────────────────────────────────────────────────
    if args.incremental:
        from pipeline.incremental_update import run_incremental_update
        summary = run_incremental_update(since=args.since, aoi=aoi)
        print(f"\nIncremental update: {summary.get('merged', 0)} total candidates")
        print(f"  New rows processed : {summary.get('updated', 0)}")
        print(f"  Timestamp          : {summary.get('timestamp', '')}")
        if summary.get("errors"):
            print(f"  Errors: {summary['errors']}")
            return 1
        return 0

    # ── Serve ──────────────────────────────────────────────────────────────────
    if args.serve:
        try:
            import uvicorn
            from api.fastapi_app import create_app
            app = create_app()
            if app is None:
                print("FastAPI not installed. Run: pip install fastapi uvicorn")
                return 1
            print(f"Starting GEO-PR-INT API on http://{args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port)
            return 0
        except ImportError as exc:
            print(f"Server dependencies missing: {exc}")
            print("Run: pip install fastapi uvicorn")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
