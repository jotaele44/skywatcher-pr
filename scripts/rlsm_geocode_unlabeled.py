#!/usr/bin/env python3
"""
OCR Pass 2: Geocode unlabeled POI candidates.

Consumes the bounded per-screenshot pixel→lat/lon transforms persisted by
``fr24.rlsm_georeference``.  This stage does not independently fit or publish a
second spatial model.  The legacy PR-wide approximation is available only via
an explicit flag and is never persisted as spatial truth.

  - Apply each accepted transform to unlabeled-candidate centroids.

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
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_georeference import (  # noqa: E402
    GEOREF_VERSION,
    load_persisted_affines,
)
from fr24.rlsm_spatial_schema import ensure_spatial_schema  # noqa: E402
from integration.geo_calibration import apply_affine, fit_affine  # noqa: E402, F401

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


# fit_affine / apply_affine now live in integration/geo_calibration.py (shared
# with the calibration's per_screenshot_affine mode); imported above.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-deg", type=float, default=0.001,
                    help="Cluster geocoded candidates by this lat/lon grid (default 0.001° ≈ 111m)")
    ap.add_argument("--min-screenshots", type=int, default=5)
    ap.add_argument("--min-aircraft", type=int, default=10)
    ap.add_argument("--max-affine-residual-deg", type=float, default=0.05,
                    help="Deprecated; persisted georeferences use a 500 m ceiling")
    ap.add_argument(
        "--allow-global-fallback",
        action="store_true",
        help="Explicitly permit the legacy approximate PR-wide transform",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    ensure_spatial_schema(conn)
    affines = load_persisted_affines(conn)
    fit_residuals = {
        int(sid): float(residual)
        for sid, residual in conn.execute(
            """SELECT screenshot_id, fit_residual_m
               FROM screenshot_georeferences
               WHERE georef_version=? AND status='located'
                 AND fit_residual_m IS NOT NULL""",
            (GEOREF_VERSION,),
        )
    }
    fits_attempted = conn.execute(
        """SELECT COUNT(*) FROM screenshot_georeferences
           WHERE georef_version=? AND method='multi_anchor_affine'""",
        (GEOREF_VERSION,),
    ).fetchone()[0]
    multi_fits_succeeded = conn.execute(
        """SELECT COUNT(*) FROM screenshot_georeferences
           WHERE georef_version=? AND status='located'
             AND method='multi_anchor_affine'""",
        (GEOREF_VERSION,),
    ).fetchone()[0]
    one_anchor_transforms = conn.execute(
        """SELECT COUNT(*) FROM screenshot_georeferences
           WHERE georef_version=? AND status='located'
             AND method='one_anchor_zoom_rung'""",
        (GEOREF_VERSION,),
    ).fetchone()[0]
    usable_transforms = len(affines)
    fits_dropped_residual = conn.execute(
        """SELECT COUNT(*) FROM screenshot_georeferences
           WHERE georef_version=? AND status IN ('rejected_residual','rejected_geometry')""",
        (GEOREF_VERSION,),
    ).fetchone()[0]
    print(
        f"[geocode] persisted transforms — attempted {fits_attempted}, "
        f"accepted multi-anchor {multi_fits_succeeded}, "
        f"one-anchor {one_anchor_transforms}, usable {usable_transforms}, "
        f"rejected {fits_dropped_residual}"
    )

    # Approximate fallback is opt-in.  It is never persisted as spatial truth.
    dims_by_sid = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT screenshot_id, width, height FROM screenshots")}
    global_affine_sids = 0
    if args.allow_global_fallback:
        for sid, (w, h) in dims_by_sid.items():
            if sid not in affines and (w, h) == (1170, 2532):
                affines[sid] = GLOBAL_AFFINE_1170_2532
                global_affine_sids += 1
        print(
            f"[geocode] explicit global-affine fallback applied to "
            f"{global_affine_sids} screenshots"
        )

    # Geocode unlabeled candidates
    cells = defaultdict(lambda: {"hits": [], "sids": set(), "ctypes": Counter(),
                                  "lats": [], "lons": []})
    geocoded = dropped_outside_pr = no_affine = 0
    for cid, sid, ctype, cx, cy, conf in conn.execute("""
        SELECT candidate_id, screenshot_id, candidate_type, centroid_x, centroid_y, confidence
        FROM unlabeled_pin_candidates
        WHERE centroid_x IS NOT NULL
    """):
        af = affines.get(sid)
        if not af:
            no_affine += 1
            continue
        lat, lon = apply_affine(af, cx, cy)
        if not (PR_BBOX[0] <= lat <= PR_BBOX[1] and PR_BBOX[2] <= lon <= PR_BBOX[3]):
            dropped_outside_pr += 1
            continue
        geocoded += 1
        gx = round(lat / args.grid_deg) * args.grid_deg
        gy = round(lon / args.grid_deg) * args.grid_deg
        key = (gx, gy, ctype)
        c = cells[key]
        c["hits"].append((cid, sid, conf))
        c["sids"].add(sid)
        c["ctypes"][ctype] += 1
        c["lats"].append(lat)
        c["lons"].append(lon)

    # Aircraft per screenshot for diversity filter
    aircraft_by_sid = defaultdict(set)
    for sid, reg in conn.execute(
        "SELECT screenshot_id, registration FROM aircraft_observations WHERE registration IS NOT NULL"
    ):
        aircraft_by_sid[sid].add(reg)

    # Surface clusters
    clusters = []
    for (gx, gy, ctype), c in cells.items():
        if len(c["sids"]) < args.min_screenshots:
            continue
        aircraft_seen = Counter()
        for sid in c["sids"]:
            for reg in aircraft_by_sid.get(sid, []):
                aircraft_seen[reg] += 1
        if len(aircraft_seen) < args.min_aircraft:
            continue
        clusters.append({
            "lat_grid": round(gx, 5),
            "lon_grid": round(gy, 5),
            "candidate_type": ctype,
            "n_distinct_screenshots": len(c["sids"]),
            "n_unique_aircraft": len(aircraft_seen),
            "n_hits": len(c["hits"]),
            "median_lat": round(median(c["lats"]), 5),
            "median_lon": round(median(c["lons"]), 5),
            "top_aircraft": ",".join(f"{r}({n})" for r, n in aircraft_seen.most_common(3)),
        })
    clusters.sort(key=lambda x: (-x["n_distinct_screenshots"], -x["n_unique_aircraft"]))

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = ["lat_grid","lon_grid","candidate_type","n_distinct_screenshots",
              "n_unique_aircraft","n_hits","median_lat","median_lon","top_aircraft"]
    with (OUTS / "intel_unlabeled_clusters_geo.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for c in clusters:
            w.writerow(c)

    # GeoJSON for top 500 clusters
    features = []
    for c in clusters[:500]:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["median_lon"], c["median_lat"]]},
            "properties": {
                "candidate_type": c["candidate_type"],
                "n_distinct_screenshots": c["n_distinct_screenshots"],
                "n_unique_aircraft": c["n_unique_aircraft"],
                "n_hits": c["n_hits"],
                "top_aircraft": c["top_aircraft"],
            },
        })
    (OUTS / "intel_unlabeled_geo.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2))

    # Audit summary
    residual_values = sorted(fit_residuals.values())
    median_residual = round(float(median(residual_values)), 2) if residual_values else None
    p90_index = min(len(residual_values) - 1, int(0.9 * len(residual_values))) if residual_values else 0
    p90_residual = round(float(residual_values[p90_index]), 2) if residual_values else None
    accuracy_note = (
        "\n> **Accuracy note:** the default path consumes only persisted transforms"
        " whose estimated error is at most 500 m. The legacy PR-wide approximation"
        " is available only through `--allow-global-fallback` and is never persisted"
        " as aircraft spatial truth.\n"
    )
    md = ["# Geocoded unlabeled POI clusters — audit\n",
          accuracy_note,
          f"\n- Screenshots assigned the global-affine fallback: **{global_affine_sids:,}**",
          "\n## Affine-fit pipeline\n",
          f"- Screenshots with ≥2 anchors: {fits_attempted:,}",
          f"- Accepted multi-anchor fits: **{multi_fits_succeeded:,}**",
          f"- One-anchor + zoom-rung recoveries: {one_anchor_transforms:,}",
          f"- Total usable persisted transforms: {usable_transforms:,}",
          f"- Rejected by geometry or >500 m error: {fits_dropped_residual:,}",
          f"- Median fit residual: **{median_residual} m**",
          f"- P90 fit residual: {p90_residual} m",
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
          "|---|---|---|---|---|---|---|"]
    for c in clusters[:25]:
        md.append(f"| {c['median_lat']} | {c['median_lon']} | {c['candidate_type']} | "
                  f"{c['n_distinct_screenshots']} | {c['n_unique_aircraft']} | {c['n_hits']} | "
                  f"{c['top_aircraft'][:50]} |")
    (OUTS / "intel_geocode_audit.md").write_text("\n".join(md) + "\n")

    conn.close()
    print(json.dumps({
        "affine_fits_succeeded": multi_fits_succeeded,
        "one_anchor_transforms": one_anchor_transforms,
        "usable_persisted_transforms": usable_transforms,
        "median_fit_residual_m": median_residual,
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
