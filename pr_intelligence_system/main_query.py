"""
main_query.py — CLI entrypoint for the ILAP query engine.

Usage:
    python main_query.py <lat> <lon> <radius_km> [--output PATH] [--trigger-pipeline] [--fetch-satellite]

Example:
    python main_query.py 18.265 -66.700 5
    python main_query.py 18.265 -66.700 5 --output /tmp/results.csv
    python main_query.py 18.265 -66.700 5 --fetch-satellite
"""

import argparse
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the ILAP geospatial analysis system for a location.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("lat", type=float, help="Latitude (WGS84, decimal degrees)")
    parser.add_argument("lon", type=float, help="Longitude (WGS84, decimal degrees)")
    parser.add_argument("radius_km", type=float, help="Query radius in kilometres")
    parser.add_argument(
        "--output", metavar="PATH", default=None,
        help="Optional path to save ILAP results as CSV",
    )
    parser.add_argument(
        "--trigger-pipeline", action="store_true", default=False,
        help="Run the full pipeline if the master dataset is missing",
    )
    parser.add_argument(
        "--fetch-satellite", action="store_true", default=False,
        help=(
            "Fetch fresh Sentinel-2 data via openEO for new AOIs and run "
            "the AOI-scoped pipeline (requires Copernicus account + OIDC auth)"
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from api.query_engine import run_query_engine

    try:
        _ilap_gdf, _summary, report_text = run_query_engine(
            lat=args.lat,
            lon=args.lon,
            radius_km=args.radius_km,
            project_root=PROJECT_ROOT,
            output_csv=args.output,
            trigger_pipeline=args.trigger_pipeline,
            fetch_satellite=args.fetch_satellite,
        )
    except Exception as exc:
        logging.getLogger(__name__).error("Query failed: %s", exc)
        sys.exit(1)

    print(report_text)
    sys.exit(0)


if __name__ == "__main__":
    main()
