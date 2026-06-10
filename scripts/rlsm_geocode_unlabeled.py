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

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
PR_BBOX = (17.7, 18.65, -67.55, -65.15)  # (lat_min, lat_max, lon_min, lon_max)

# Global-affine fallback constants for FR24 default PR-wide view on iPhone-portrait
# (1170x2532). Approximate — replace with per-screenshot fit after running
# scripts/rlsm_reocr_label_layer.py (which populates true word-level centroids).
# Derived from PR-overview map zoom level: 1170px wide ≈ 1.8° lon (~200km)
GLOBAL_AFFINE_1170_2532 = (
    -67.35,    # lon0 (at px=0)
    0.00154,   # dlon_dx (° per pixel)
    18.6576,   # lat0 (at py=0)
    -0.000538, # dlat_dy (° per pixel — negative: pixel y grows downward, lat grows upward)
)


def _ascii_up(s: str) -> str:
    if not s: return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).upper().strip()


def fit_affine(pixel_xy: list[tuple[float, float]],
               geo_latlon: list[tuple[float, float]]):
    """4-parameter affine fit: returns (lon0, dlon_dx, lat0, dlat_dy).
    Uses least-squares via numpy. Requires ≥2 anchors."""
    import numpy as np
    n = len(pixel_xy)
    if n < 2: return None
    px = np.array([p[0] for p in pixel_xy], dtype=float)
    py = np.array([p[1] for p in pixel_xy], dtype=float)
    lats = np.array([g[0] for g in geo_latlon], dtype=float)
    lons = np.array([g[1] for g in geo_latlon], dtype=float)
    # lon = a + b*px      lat = c + d*py
    A_lon = np.column_stack([np.ones(n), px])
    A_lat = np.column_stack([np.ones(n), py])
    try:
        (a, b), *_ = np.linalg.lstsq(A_lon, lons, rcond=None)
        (c, d), *_ = np.linalg.lstsq(A_lat, lats, rcond=None)
        # Reasonable scale sanity (PR is ~250 km wide ≈ 2.5° lon at this latitude)
        if abs(b) < 1e-7 or abs(d) < 1e-7: return None
        return (a, b, c, d)
    except Exception:
        return None


def apply_affine(affine, px: float, py: float):
    a, b, c, d = affine
    return c + d * py, a + b * px   # lat, lon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-deg", type=float, default=0.001,
                    help="Cluster geocoded candidates by this lat/lon grid (default 0.001° ≈ 111m)")
    ap.add_argument("--min-screenshots", type=int, default=5)
    ap.add_argument("--min-aircraft", type=int, default=10)
    ap.add_argument("--max-affine-residual-deg", type=float, default=0.05,
                    help="Drop screenshots where affine fit residual > this many degrees")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)

    # Build lat/lon lookup from places.geojson + georef_anchors
    geo_lookup = {}
    gj = json.load((REPO / "data" / "places.geojson").open())
    for f in gj.get("features", []):
        props = f.get("properties", {})
        name = (props.get("NAME") or "").upper().strip()
        try:
            lat = float(props.get("INTPTLAT") or 0); lon = float(props.get("INTPTLON") or 0)
        except (TypeError, ValueError): continue
        if name and lat and lon:
            geo_lookup[_ascii_up(name)] = (lat, lon)
    for r in conn.execute("SELECT name, lat, lon FROM geo_anchors WHERE lat IS NOT NULL"):
        geo_lookup[_ascii_up(r[0])] = (r[1], r[2])

    # Per-screenshot anchor data
    anchors_by_sid = defaultdict(list)
    for sid, label, cx, cy in conn.execute("""
        SELECT screenshot_id, normalized_label, centroid_x, centroid_y
        FROM labeled_pois
        WHERE centroid_x IS NOT NULL AND poi_type_guess != 'unknown_label_candidate'
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
        seen = set(); dedup_p = []; dedup_g = []
        for p, g in zip(pixel_xy, geo_latlon):
            key = (round(p[0], 1), round(p[1], 1))
            if key not in seen:
                seen.add(key); dedup_p.append(p); dedup_g.append(g)
        if len(dedup_p) < 2:
            continue
        af = fit_affine(dedup_p, dedup_g)
        if af is None:
            continue
        # Compute residuals
        residuals = []
        for (px, py), (lat, lon) in zip(dedup_p, dedup_g):
            est_lat, est_lon = apply_affine(af, px, py)
            residuals.append(((est_lat - lat) ** 2 + (est_lon - lon) ** 2) ** 0.5)
        med_res = float(np.median(residuals))
        if med_res > args.max_affine_residual_deg:
            fits_dropped_residual += 1
            continue
        affines[sid] = af
        fit_residuals[sid] = med_res
        fits_succeeded += 1

    print(f"[geocode] affine fits — attempted {fits_attempted}, succeeded {fits_succeeded}, "
          f"dropped (residual>{args.max_affine_residual_deg}°) {fits_dropped_residual}")

    # Fallback: load screenshot dimensions and apply GLOBAL affine for default-zoom PR-wide views
    dims_by_sid = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT screenshot_id, width, height FROM screenshots")}
    global_affine_sids = 0
    if not affines:
        print(f"[geocode] no per-screenshot affines available — falling back to "
              f"global PR-wide approximation for 1170x2532 default-zoom screenshots")
        for sid, (w, h) in dims_by_sid.items():
            if (w, h) == (1170, 2532):
                affines[sid] = GLOBAL_AFFINE_1170_2532
                global_affine_sids += 1
        print(f"[geocode] global-affine fallback applied to {global_affine_sids} screenshots")

    # Geocode unlabeled candidates
    cells = defaultdict(lambda: {"hits": [], "sids": set(), "ctypes": Counter(),
                                  "lats": [], "lons": []})
    geocoded = dropped_outside_pr = no_affine = 0
    for cid, sid, ctype, cx, cy, conf in conn.execute("""
        SELECT candidate_id, screenshot_id, candidate_type, centroid_x, centroid_y, confidence
        FROM unlabeled_poi_candidates
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
        c["lats"].append(lat); c["lons"].append(lon)

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
    median_residual = round(float(np.median(list(fit_residuals.values()))), 5) if fit_residuals else None
    p90_residual    = round(float(np.percentile(list(fit_residuals.values()), 90)), 5) if fit_residuals else None
    md = ["# Geocoded unlabeled POI clusters — audit\n",
          "\n> **Accuracy note:** This run uses the GLOBAL PR-wide affine fallback because "
          "the original POI extractor stored zone-center as centroid for all labels on a "
          "screenshot (not per-word boxes). For per-screenshot accuracy, run "
          "`scripts/rlsm_reocr_label_layer.py` on your Mac first — that populates "
          "true word-level pixel centroids, then re-running this script will use the "
          "much more accurate per-screenshot affine fits.\n",
          f"\n- Screenshots assigned the global-affine fallback: **{global_affine_sids:,}**",
          f"\n## Affine-fit pipeline\n",
          f"- Screenshots with ≥2 anchors: {fits_attempted:,}",
          f"- Screenshots with successful affine fit: **{fits_succeeded:,}**",
          f"- Dropped (residual > {args.max_affine_residual_deg}°): {fits_dropped_residual:,}",
          f"- Median fit residual: **{median_residual}°** (~{(median_residual or 0)*111:.1f} km)",
          f"- P90 fit residual: {p90_residual}°",
          f"\n## Geocoding\n",
          f"- Unlabeled candidates with usable affine: {geocoded + dropped_outside_pr:,}",
          f"- Candidates outside PR bbox: {dropped_outside_pr:,}",
          f"- Candidates without per-screenshot affine: {no_affine:,}",
          f"- Successfully geocoded inside PR: **{geocoded:,}**",
          f"\n## Clusters\n",
          f"- Total geocoded grid cells: {len(cells):,}",
          f"- After min-screenshot ({args.min_screenshots}) + min-aircraft ({args.min_aircraft}) filter: **{len(clusters):,}**",
          f"\n## Top 25 clusters\n",
          "| lat | lon | type | screenshots | aircraft | hits | top aircraft |",
          "|---|---|---|---|---|---|---|"]
    for c in clusters[:25]:
        md.append(f"| {c['median_lat']} | {c['median_lon']} | {c['candidate_type']} | "
                  f"{c['n_distinct_screenshots']} | {c['n_unique_aircraft']} | {c['n_hits']} | "
                  f"{c['top_aircraft'][:50]} |")
    (OUTS / "intel_geocode_audit.md").write_text("\n".join(md) + "\n")

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
