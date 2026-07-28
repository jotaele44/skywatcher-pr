#!/usr/bin/env python3
"""
OCR Pass 2: Geocode unlabeled POI candidates.

Per-screenshot pixel→lat/lon affine fit:
  - For each screenshot with ≥2 labeled POIs (vocab-matched municipality
    or anchor) whose pixel centroid is known AND whose lat/lon is known
    from places.geojson, solve a 4-parameter affine transform:
       lon = lon0 + dlon_per_px * pixel_x
       lat = lat0 + dlat_per_px * pixel_y   (dlat_per_px is negative; pixel y grows downward)

  - Apply the per-screenshot transform to each unlabeled candidate's
    centroid, yielding (lat, lon).

  - Filter to candidates that geocode inside the PR bounding box:
       lat ∈ [17.8, 18.6], lon ∈ [-67.5, -65.2]

  - Cluster geocoded candidates by 100m grid (≈0.0009° latitude) to find
    persistent features. A cluster needs ≥5 distinct screenshots, ≥10
    unique aircraft, to clear UI-overlay false positives.

Output:
  - outputs/intel_unlabeled_clusters_geo.csv       per-cluster lat/lon + stats
  - outputs/intel_unlabeled_geo.geojson            QGIS/Google Earth import
  - outputs/intel_geocode_audit.md                 per-screenshot fit quality

CLI:
    python3 scripts/rlsm_geocode_unlabeled.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from integration.geo_calibration import apply_affine, fit_affine

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
PR_BBOX = (17.7, 18.65, -67.55, -65.15)  # (lat_min, lat_max, lon_min, lon_max)

# Global-affine fallback constants for FR24 default PR-wide view on iPhone-portrait
# (1170x2532). Approximate — used only for screenshots that still lack per-word
# pin centroids. The label extractor now writes true word-level geometry at
# extraction time (fr24/rlsm_extractors.extract_labeled_pins), so a corpus
# processed by the current pipeline gets a per-screenshot fit instead.
# Derived from PR-overview map zoom level: 1170px wide ≈ 1.8° lon (~200km)
GLOBAL_AFFINE_1170_2532 = (
    -67.35,    # lon0 (at px=0)
    0.00154,   # dlon_dx (° per pixel)
    18.6576,   # lat0 (at py=0)
    -0.000538, # dlat_dy (° per pixel — negative: pixel y grows downward, lat grows upward)
)


def _ascii_up(s: str) -> str:
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    ).upper().strip()


# fit_affine / apply_affine live in integration/geo_calibration.py (shared
# with the calibration's per_screenshot_affine mode); imported above.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--grid-deg",
        type=float,
        default=0.001,
        help="Cluster geocoded candidates by this lat/lon grid (default 0.001° ≈ 111m)",
    )
    ap.add_argument("--min-screenshots", type=int, default=5)
    ap.add_argument("--min-aircraft", type=int, default=10)
    ap.add_argument(
        "--max-affine-residual-deg",
        type=float,
        default=0.05,
        help="Drop screenshots where affine fit residual > this many degrees",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(DB)

    # Build lat/lon lookup from places.geojson + georef_anchors
    geo_lookup = {}
    gj = json.load((REPO / "data" / "places.geojson").open())
    for feature in gj.get("features", []):
        props = feature.get("properties", {})
        name = (props.get("NAME") or "").upper().strip()
        try:
            lat = float(props.get("INTPTLAT") or 0)
            lon = float(props.get("INTPTLON") or 0)
        except (TypeError, ValueError):
            continue
        if name and lat and lon:
            geo_lookup[_ascii_up(name)] = (lat, lon)
    for row in conn.execute("SELECT name, lat, lon FROM geo_anchors WHERE lat IS NOT NULL"):
        geo_lookup[_ascii_up(row[0])] = (row[1], row[2])

    # Per-screenshot anchor data
    anchors_by_sid = defaultdict(list)
    for sid, label, cx, cy in conn.execute("""
        SELECT screenshot_id, normalized_label, centroid_x, centroid_y
        FROM labeled_pins
        WHERE centroid_x IS NOT NULL AND pin_type_guess != 'unknown_label_candidate'
    """):
        latlon = geo_lookup.get(_ascii_up(label))
        if latlon and cx and cy:
            anchors_by_sid[sid].append((cx, cy, latlon[0], latlon[1]))

    # Fit affine per screenshot
    affines = {}
    fit_residuals = {}
    fits_attempted = fits_succeeded = fits_dropped_residual = 0
    import numpy as np

    for sid, anchors in anchors_by_sid.items():
        if len(anchors) < 2:
            continue
        fits_attempted += 1
        pixel_xy = [(a[0], a[1]) for a in anchors]
        geo_latlon = [(a[2], a[3]) for a in anchors]
        # Drop duplicates (same anchor labeled twice in a screenshot)
        seen = set()
        dedup_p = []
        dedup_g = []
        for pixel, geo in zip(pixel_xy, geo_latlon, strict=False):
            key = (round(pixel[0], 1), round(pixel[1], 1))
            if key not in seen:
                seen.add(key)
                dedup_p.append(pixel)
                dedup_g.append(geo)
        if len(dedup_p) < 2:
            continue
        affine = fit_affine(dedup_p, dedup_g)
        if affine is None:
            continue
        residuals = []
        for (px, py), (lat, lon) in zip(dedup_p, dedup_g, strict=False):
            est_lat, est_lon = apply_affine(affine, px, py)
            residuals.append(((est_lat - lat) ** 2 + (est_lon - lon) ** 2) ** 0.5)
        med_res = float(np.median(residuals))
        if med_res > args.max_affine_residual_deg:
            fits_dropped_residual += 1
            continue
        affines[sid] = affine
        fit_residuals[sid] = med_res
        fits_succeeded += 1

    print(
        f"[geocode] affine fits — attempted {fits_attempted}, succeeded {fits_succeeded}, "
        f"dropped (residual>{args.max_affine_residual_deg}°) {fits_dropped_residual}"
    )

    # Fallback: load screenshot dimensions and apply GLOBAL affine for default-zoom PR-wide views
    dims_by_sid = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT screenshot_id, width, height FROM screenshots")
    }
    global_affine_sids = 0
    if not affines:
        print(
            "[geocode] no per-screenshot affines available — falling back to "
            "global PR-wide approximation for 1170x2532 default-zoom screenshots"
        )
        for sid, (width, height) in dims_by_sid.items():
            if (width, height) == (1170, 2532):
                affines[sid] = GLOBAL_AFFINE_1170_2532
                global_affine_sids += 1
        print(f"[geocode] global-affine fallback applied to {global_affine_sids} screenshots")

    # Geocode unlabeled candidates
    cells = defaultdict(
        lambda: {"hits": [], "sids": set(), "ctypes": Counter(), "lats": [], "lons": []}
    )
    geocoded = dropped_outside_pr = no_affine = 0
    for cid, sid, ctype, cx, cy, conf in conn.execute("""
        SELECT candidate_id, screenshot_id, candidate_type, centroid_x, centroid_y, confidence
        FROM unlabeled_pin_candidates
        WHERE centroid_x IS NOT NULL
    """):
        affine = affines.get(sid)
        if not affine:
            no_affine += 1
            continue
        lat, lon = apply_affine(affine, cx, cy)
        if not (PR_BBOX[0] <= lat <= PR_BBOX[1] and PR_BBOX[2] <= lon <= PR_BBOX[3]):
            dropped_outside_pr += 1
            continue
        geocoded += 1
        gx = round(lat / args.grid_deg) * args.grid_deg
        gy = round(lon / args.grid_deg) * args.grid_deg
        key = (gx, gy, ctype)
        cell = cells[key]
        cell["hits"].append((cid, sid, conf))
        cell["sids"].add(sid)
        cell["ctypes"][ctype] += 1
        cell["lats"].append(lat)
        cell["lons"].append(lon)

    # Aircraft per screenshot for diversity filter
    aircraft_by_sid = defaultdict(set)
    for sid, registration in conn.execute(
        "SELECT screenshot_id, registration FROM aircraft_observations WHERE registration IS NOT NULL"
    ):
        aircraft_by_sid[sid].add(registration)

    # Surface clusters
    clusters = []
    for (gx, gy, ctype), cell in cells.items():
        if len(cell["sids"]) < args.min_screenshots:
            continue
        aircraft_seen = Counter()
        for sid in cell["sids"]:
            for registration in aircraft_by_sid.get(sid, []):
                aircraft_seen[registration] += 1
        if len(aircraft_seen) < args.min_aircraft:
            continue
        clusters.append({
            "lat_grid": round(gx, 5),
            "lon_grid": round(gy, 5),
            "candidate_type": ctype,
            "n_distinct_screenshots": len(cell["sids"]),
            "n_unique_aircraft": len(aircraft_seen),
            "n_hits": len(cell["hits"]),
            "median_lat": round(median(cell["lats"]), 5),
            "median_lon": round(median(cell["lons"]), 5),
            "top_aircraft": ",".join(
                f"{registration}({count})"
                for registration, count in aircraft_seen.most_common(3)
            ),
        })
    clusters.sort(key=lambda value: (-value["n_distinct_screenshots"], -value["n_unique_aircraft"]))

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = [
        "lat_grid",
        "lon_grid",
        "candidate_type",
        "n_distinct_screenshots",
        "n_unique_aircraft",
        "n_hits",
        "median_lat",
        "median_lon",
        "top_aircraft",
    ]
    with (OUTS / "intel_unlabeled_clusters_geo.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for cluster in clusters:
            writer.writerow(cluster)

    # GeoJSON for top 500 clusters
    features = []
    for cluster in clusters[:500]:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [cluster["median_lon"], cluster["median_lat"]],
            },
            "properties": {
                "candidate_type": cluster["candidate_type"],
                "n_distinct_screenshots": cluster["n_distinct_screenshots"],
                "n_unique_aircraft": cluster["n_unique_aircraft"],
                "n_hits": cluster["n_hits"],
                "top_aircraft": cluster["top_aircraft"],
            },
        })
    (OUTS / "intel_unlabeled_geo.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )

    # Audit summary
    median_residual = (
        round(float(np.median(list(fit_residuals.values()))), 5)
        if fit_residuals
        else None
    )
    p90_residual = (
        round(float(np.percentile(list(fit_residuals.values()), 90)), 5)
        if fit_residuals
        else None
    )
    accuracy_note = (
        "\n> **Accuracy note:** Screenshots counted below under the GLOBAL PR-wide affine"
        " fallback have no per-word pin centroids — they were extracted before the label"
        " extractor recorded word-level geometry. To upgrade them to per-screenshot fits,"
        " re-run OCR with word boxes and re-extract pins"
        " (`./run-rlsm.sh --stage ocr --reocr-boxes` then `./run-rlsm.sh --stage pins`),"
        " then run this script again.\n"
    )
    markdown = [
        "# Geocoded unlabeled POI clusters — audit\n",
        accuracy_note,
        f"\n- Screenshots assigned the global-affine fallback: **{global_affine_sids:,}**",
        "\n## Affine-fit pipeline\n",
        f"- Screenshots with ≥2 anchors: {fits_attempted:,}",
        f"- Screenshots with successful affine fit: **{fits_succeeded:,}**",
        f"- Dropped (residual > {args.max_affine_residual_deg}°): {fits_dropped_residual:,}",
        f"- Median fit residual: **{median_residual}°** (~{(median_residual or 0) * 111:.1f} km)",
        f"- P90 fit residual: {p90_residual}°",
        "\n## Geocoding\n",
        f"- Unlabeled candidates with usable affine: {geocoded + dropped_outside_pr:,}",
        f"- Candidates outside PR bbox: {dropped_outside_pr:,}",
        f"- Candidates without per-screenshot affine: {no_affine:,}",
        f"- Successfully geocoded inside PR: **{geocoded:,}**",
        "\n## Clusters\n",
        f"- Total geocoded grid cells: {len(cells):,}",
        f"- After min-screenshot ({args.min_screenshots}) + min-aircraft ({args.min_aircraft}) filter: **{len(clusters):,}**",
        "\n## Top 25 clusters\n",
        "| lat | lon | type | screenshots | aircraft | hits | top aircraft |",
        "|---|---|---|---|---|---|---|",
    ]
    for cluster in clusters[:25]:
        markdown.append(
            f"| {cluster['median_lat']} | {cluster['median_lon']} | {cluster['candidate_type']} | "
            f"{cluster['n_distinct_screenshots']} | {cluster['n_unique_aircraft']} | "
            f"{cluster['n_hits']} | {cluster['top_aircraft'][:50]} |"
        )
    (OUTS / "intel_geocode_audit.md").write_text("\n".join(markdown) + "\n")

    conn.close()
    print(json.dumps({
        "affine_fits_succeeded": fits_succeeded,
        "median_fit_residual_deg": median_residual,
        "geocoded_candidates": geocoded,
        "clusters_emitted": len(clusters),
        "outputs": [
            "outputs/intel_unlabeled_clusters_geo.csv",
            "outputs/intel_unlabeled_geo.geojson",
            "outputs/intel_geocode_audit.md",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
