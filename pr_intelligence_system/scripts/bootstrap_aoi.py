"""
bootstrap_aoi.py — Seed the master dataset with real satellite data for an AOI.

Downloads Sentinel-2 NDVI and Copernicus DEM for the specified location via
openEO, saves them to data/raw/, then runs the full pipeline to produce a
real (non-synthetic) final_anomaly_ranked.csv.

Run this once before using the query engine on a new region.

Usage:
    python scripts/bootstrap_aoi.py <lat> <lon> <radius_km>

Example:
    python scripts/bootstrap_aoi.py 18.265 -66.700 25
"""

import argparse
import logging
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap the master dataset with real satellite data for an AOI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("lat", type=float, help="Centre latitude (WGS84)")
    parser.add_argument("lon", type=float, help="Centre longitude (WGS84)")
    parser.add_argument("radius_km", type=float, help="Radius in kilometres")
    parser.add_argument(
        "--days-back", type=int, default=90,
        help="Temporal window for Sentinel-2 search (default: 90 days)",
    )
    parser.add_argument("--verbose", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    from core.aoi import create_aoi
    from core.memory import generate_aoi_id
    from core.ingest.fetcher import fetch_for_aoi

    aoi_gdf = create_aoi(args.lat, args.lon, args.radius_km)
    aoi_id = generate_aoi_id(args.lat, args.lon, args.radius_km)
    raw_dir = os.path.join(PROJECT_ROOT, "data", "raw", f"bootstrap_{aoi_id}")

    log.info("Bootstrapping AOI %s  (%.4f, %.4f)  r=%.1f km", aoi_id, args.lat, args.lon, args.radius_km)
    log.info("Satellite data will be saved to: %s", raw_dir)

    # Step 1: fetch satellite data into data/raw/
    tif_paths = fetch_for_aoi(aoi_gdf, aoi_id, raw_dir, days_back=args.days_back)
    if not tif_paths:
        log.error("No satellite data returned. Check auth and AOI coverage.")
        sys.exit(1)
    log.info("Downloaded %d GeoTIFF file(s).", len(tif_paths))

    # Step 2: run full pipeline — scan_directory() recurses into subdirs,
    # so the files in data/raw/bootstrap_{aoi_id}/ will be found automatically.
    log.info("Running full pipeline (run_all.py)...")
    run_all = os.path.join(PROJECT_ROOT, "run_all.py")
    result = subprocess.run(
        [sys.executable, run_all],
        cwd=PROJECT_ROOT,
        capture_output=not args.verbose,
        text=True,
    )
    if result.returncode != 0:
        log.error("Pipeline failed:\n%s", result.stderr if result.stderr else "(no output)")
        sys.exit(1)

    master = os.path.join(PROJECT_ROOT, "data", "output", "final_anomaly_ranked.csv")
    log.info("Bootstrap complete. Master dataset: %s", master)
    print(f"\nDone. Run queries with:\n  python main_query.py {args.lat} {args.lon} 5")


if __name__ == "__main__":
    main()
