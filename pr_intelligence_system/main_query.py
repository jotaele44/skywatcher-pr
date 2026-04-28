"""
main_query.py — CLI entrypoint for the ILAP query engine.

Usage (by coordinates):
    python main_query.py <lat> <lon> <radius_km> [options]

Usage (by location name):
    python main_query.py --location "San Juan" [--radius KM] [options]

Examples:
    python main_query.py 18.265 -66.700 5
    python main_query.py --location "Arecibo" --aspect coastal riverine
    python main_query.py --location "Ponce" --fetch-satellite --publish-felt
    python main_query.py 18.265 -66.700 20 --aspect mountainous --output /tmp/out.csv

Aspect names: coastal, mountainous, riverine, karst, urban,
              high-confidence, corridor, flat, sloped

Environment variables:
    FELT_API_KEY    — Felt personal access token (for --publish-felt)
    CDSE_USER       — Copernicus username (for --fetch-sar)
    CDSE_PASSWORD   — Copernicus password (for --fetch-sar)
"""

import argparse
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the ILAP geospatial analysis system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- Coordinate or location name (mutually exclusive) ---
    coord_group = parser.add_argument_group("coordinates (alternative to --location)")
    coord_group.add_argument("lat", nargs="?", type=float, default=None,
                             help="Latitude (WGS84, decimal degrees)")
    coord_group.add_argument("lon", nargs="?", type=float, default=None,
                             help="Longitude (WGS84, decimal degrees)")
    coord_group.add_argument("radius_km", nargs="?", type=float, default=None,
                             help="Query radius in kilometres")

    parser.add_argument(
        "--location", metavar="NAME", default=None,
        help="Place name to geocode (e.g. 'San Juan', 'El Yunque')",
    )
    parser.add_argument(
        "--radius", type=float, default=None, metavar="KM",
        help="Override the default radius when using --location",
    )

    # --- Aspect filtering ---
    parser.add_argument(
        "--aspect", nargs="+", default=None, metavar="NAME",
        help=(
            "One or more aspect filters applied to ILAP results. "
            "Valid: coastal, mountainous, riverine, karst, urban, "
            "high-confidence, corridor, flat, sloped"
        ),
    )

    # --- Data fetch flags ---
    parser.add_argument(
        "--fetch-satellite", action="store_true", default=False,
        help="Fetch Sentinel-2 + DEM via openEO for new AOIs (requires Copernicus OIDC auth)",
    )
    parser.add_argument(
        "--fetch-sar", action="store_true", default=False,
        help=(
            "Fetch Sentinel-1 SAR backscatter via Copernicus ODP "
            "(requires CDSE_USER / CDSE_PASSWORD env vars; implies --fetch-satellite)"
        ),
    )
    parser.add_argument(
        "--trigger-pipeline", action="store_true", default=False,
        help="Run the full pipeline if the master dataset is missing",
    )

    # --- Output flags ---
    parser.add_argument(
        "--output", metavar="PATH", default=None,
        help="Save ILAP results as CSV to this path",
    )
    parser.add_argument(
        "--publish-felt", action="store_true", default=False,
        help="Publish ILAP results to a new Felt map (requires FELT_API_KEY env var)",
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
    log = logging.getLogger(__name__)

    # --- Resolve lat/lon/radius ---
    lat = lon = radius_km = None

    if args.location:
        try:
            from core.location import resolve_location
            loc = resolve_location(args.location, radius_km=args.radius)
        except Exception as exc:
            log.error("Location resolution failed: %s", exc)
            sys.exit(1)
        lat = loc["lat"]
        lon = loc["lon"]
        radius_km = loc["radius_km"]
        log.info(
            "Resolved '%s' → %s (%.4f, %.4f), radius %.1f km",
            args.location, loc["display_name"], lat, lon, radius_km,
        )
    elif args.lat is not None and args.lon is not None and args.radius_km is not None:
        lat = args.lat
        lon = args.lon
        radius_km = args.radius_km
        if args.radius is not None:
            radius_km = args.radius
    else:
        logging.getLogger(__name__).error(
            "Provide either positional (lat lon radius_km) or --location NAME."
        )
        sys.exit(1)

    from api.query_engine import run_query_engine

    try:
        _ilap_gdf, _summary, report_text = run_query_engine(
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            project_root=PROJECT_ROOT,
            output_csv=args.output,
            trigger_pipeline=args.trigger_pipeline,
            fetch_satellite=args.fetch_satellite,
            fetch_sar=args.fetch_sar,
            aspects=args.aspect,
            publish_felt=args.publish_felt,
        )
    except Exception as exc:
        log.error("Query failed: %s", exc)
        sys.exit(1)

    print(report_text)
    sys.exit(0)


if __name__ == "__main__":
    main()
