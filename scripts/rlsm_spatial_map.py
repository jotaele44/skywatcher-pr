#!/usr/bin/env python3
"""
Phase A: Spatial / geographic. Produces:

  - outputs/intel_spatial_map.html       interactive Leaflet map showing every
                                          POI sized by sightings, colored by
                                          dominant operator, with popup detail
  - outputs/intel_pois.geojson           GeoJSON export for QGIS / Google Earth
  - outputs/intel_pois_by_municipality.csv  per-municipality aircraft footprint
  - outputs/intel_coverage_gaps.csv      PR municipalities NEVER observed (gaps)

Uses lat/lon from data/places.geojson (TIGER 2025) + configs/georef_anchors.csv.

CLI:
    python3 scripts/rlsm_spatial_map.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def _ascii_up(s: str) -> str:
    """Strip diacritics and uppercase: BAYAMÓN -> BAYAMON, AÑASCO -> ANASCO."""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).upper().strip()

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

# Color palette per dominant operator (cycle through these for less-common operators)
OPERATOR_COLORS = {
    "PREPA": "#0066cc",                # blue
    "Blue Aviation": "#3399ff",         # light blue
    "Southwest Aviation": "#cc6600",   # orange
    "Private": "#999999",              # gray
    "Caribbean Helicopters": "#009933",# green
    "USCG": "#cc0000",                 # red
    "DEPARTMENT OF HOMELAND SECURITY": "#660000",  # dark red
    "PUERTO RICO ELECTRIC POWER AUTHORITY": "#0066cc",
    "ADMINISTRACION DE SERVICIOS GENERALES": "#9933cc",  # purple
    "MASTER LINK CORP": "#000099",                       # navy
    "UNITED STATES DEPARTMENT OF COMMERCE": "#ff6600",   # orange-red (NOAA)
}
FALLBACK_PALETTE = ["#7f7f7f", "#e377c2", "#bcbd22", "#17becf", "#ff7f0e",
                    "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def color_for(operator: str, palette_idx: list[int]) -> str:
    if operator in OPERATOR_COLORS:
        return OPERATOR_COLORS[operator]
    idx = palette_idx[0] % len(FALLBACK_PALETTE)
    palette_idx[0] += 1
    return FALLBACK_PALETTE[idx]


def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    conn = sqlite3.connect(DB)

    # Load POI lat/lon from places.geojson + georef_anchors
    poi_geo = {}
    # Map both diacritic-stripped AND original uppercase form to (lat, lon, type, display_name)
    gj = json.load((REPO / "data" / "places.geojson").open())
    for f in gj.get("features", []):
        props = f.get("properties", {})
        name = (props.get("NAME") or "").upper().strip()
        ascii_name = _ascii_up(name)
        try:
            lat = float(props.get("INTPTLAT") or 0)
            lon = float(props.get("INTPTLON") or 0)
        except (TypeError, ValueError):
            lat = lon = 0
        if name and lat and lon:
            poi_geo[name] = (lat, lon, "municipality")
            # Also store ASCII version pointing to same record (for join robustness)
            if ascii_name and ascii_name != name:
                poi_geo[ascii_name] = (lat, lon, "municipality")
    anchors_csv = REPO / "configs" / "georef_anchors.csv"
    if anchors_csv.exists():
        for r in csv.DictReader(anchors_csv.open()):
            for key in (r.get("anchor_id",""), r.get("name","")):
                k = key.upper().strip()
                try:
                    lat = float(r["lat"]); lon = float(r["lon"])
                    if k and lat and lon:
                        poi_geo.setdefault(k, (lat, lon, "airport_or_anchor"))
                except (KeyError, TypeError, ValueError):
                    pass

    # Per-POI sightings and top operator (key by ASCII-uppercase for diacritic tolerance)
    poi_data = defaultdict(lambda: {"sightings": 0, "aircraft": Counter(),
                                     "operators": Counter()})
    for r in conn.execute("""
        SELECT lp.normalized_label, a.registration, a.operator_text_manual
        FROM labeled_pins lp
        JOIN aircraft_observations a ON a.screenshot_id = lp.screenshot_id
        WHERE lp.pin_type_guess != 'unknown_label_candidate'
    """):
        norm, reg, op = r
        d = poi_data[_ascii_up(norm)]
        d["sightings"] += 1
        if reg: d["aircraft"][reg] += 1
        if op: d["operators"][op] += 1

    # Merge to (lat, lon, sightings, ...) using ASCII-tolerant lookup
    plotted_pois = []
    for norm, info in poi_data.items():
        # Try direct, then ASCII-stripped lookup
        if norm in poi_geo:
            lat, lon, ptype = poi_geo[norm]
        else:
            ascii_norm = _ascii_up(norm)
            if ascii_norm in poi_geo:
                lat, lon, ptype = poi_geo[ascii_norm]
            else:
                continue
        top_op = info["operators"].most_common(1)[0][0] if info["operators"] else "?"
        top_air = ", ".join(f"{r}({n})" for r, n in info["aircraft"].most_common(3))
        plotted_pois.append({
            "name": norm, "lat": lat, "lon": lon, "type": ptype,
            "sightings": info["sightings"], "top_operator": top_op,
            "top_aircraft": top_air, "n_aircraft": len(info["aircraft"]),
        })

    # GeoJSON
    palette_idx = [0]
    features = []
    for p in plotted_pois:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "name": p["name"], "type": p["type"], "sightings": p["sightings"],
                "top_operator": p["top_operator"], "top_aircraft": p["top_aircraft"],
                "n_unique_aircraft": p["n_aircraft"],
                "marker_color": color_for(p["top_operator"], palette_idx),
            },
        })
    OUTS.mkdir(parents=True, exist_ok=True)
    (OUTS / "intel_pois.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2))

    # Per-municipality CSV with coverage flag (dedupe to canonical display name)
    # Use ASCII-keyed unique set: a single municipality might appear in poi_geo
    # under both ASCII and diacritic forms — only count once.
    all_pr_munis_ascii = {_ascii_up(n) for n, info in poi_geo.items() if info[2] == "municipality"}
    visited_munis_ascii = {_ascii_up(p["name"]) for p in plotted_pois if p["type"] == "municipality"}
    unvisited_ascii = sorted(all_pr_munis_ascii - visited_munis_ascii)
    # Map back to one canonical display name per ASCII key
    ascii_to_display = {}
    for n, info in poi_geo.items():
        if info[2] == "municipality":
            ascii_to_display.setdefault(_ascii_up(n), n)
    unvisited = [ascii_to_display[a] for a in unvisited_ascii if a in ascii_to_display]
    all_pr_munis = all_pr_munis_ascii  # for count-only use later

    with (OUTS / "intel_pois_by_municipality.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["name", "lat", "lon", "sightings", "n_unique_aircraft",
                    "top_operator", "top_aircraft"])
        for p in sorted(plotted_pois, key=lambda x: -x["sightings"]):
            if p["type"] != "municipality": continue
            w.writerow([p["name"], p["lat"], p["lon"], p["sightings"],
                        p["n_aircraft"], p["top_operator"], p["top_aircraft"]])

    # Coverage gaps CSV
    with (OUTS / "intel_coverage_gaps.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["municipality", "lat", "lon"])
        for muni in unvisited:
            lat, lon, _ = poi_geo[muni]
            w.writerow([muni, lat, lon])

    # HTML map — single-file, Leaflet CDN
    palette_idx = [0]  # reset
    markers_js = []
    for p in plotted_pois:
        # Radius proportional to log(sightings)
        import math
        radius = max(3, min(20, 3 + math.log1p(p["sightings"]) * 2.5))
        color = color_for(p["top_operator"], palette_idx)
        popup = (f"<b>{p['name']}</b><br>"
                 f"Type: {p['type']}<br>"
                 f"Sightings: <b>{p['sightings']}</b><br>"
                 f"Top operator: <b>{p['top_operator']}</b><br>"
                 f"Top aircraft: {p['top_aircraft']}<br>"
                 f"Unique aircraft: {p['n_aircraft']}").replace('"', "&quot;")
        markers_js.append(
            f'L.circleMarker([{p["lat"]}, {p["lon"]}], {{radius:{radius:.1f}, color:"{color}",'
            f' fillColor:"{color}", fillOpacity:0.6, weight:1}}).bindPopup("{popup}").addTo(map);')

    # Coverage-gap markers (unvisited municipalities, faint gray hollow circles)
    gap_markers_js = []
    for muni in unvisited[:200]:  # cap for browser perf
        lat, lon, _ = poi_geo[muni]
        gap_markers_js.append(
            f'L.circleMarker([{lat}, {lon}], {{radius:3, color:"#cccccc", fillColor:"#ffffff",'
            f' fillOpacity:0.3, weight:1}}).bindPopup("UNVISITED: {muni}").addTo(gaps);')

    html = f"""<!DOCTYPE html>
<html><head>
<title>RLSM PR Operations Map</title>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body{{margin:0;font-family:-apple-system,sans-serif;}}
  #map{{height:100vh;width:100%;}}
  .legend{{background:white;padding:10px;border:1px solid #888;font-size:12px;line-height:1.6;}}
  .legend .sw{{display:inline-block;width:14px;height:14px;border-radius:50%;vertical-align:middle;margin-right:6px;}}
  h1{{position:fixed;top:10px;left:50px;background:rgba(255,255,255,0.9);padding:6px 12px;border-radius:6px;z-index:1000;font-size:16px;margin:0;}}
</style>
</head><body>
<h1>RLSM Puerto Rico operations map — {len(plotted_pois)} POIs, {len(unvisited)} unvisited municipalities</h1>
<div id="map"></div>
<script>
var map = L.map('map').setView([18.22, -66.59], 9);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 18,
  attribution: '© OpenStreetMap contributors'
}}).addTo(map);
var gaps = L.layerGroup().addTo(map);
{chr(10).join(gap_markers_js)}
{chr(10).join(markers_js)}
var legend = L.control({{position: 'bottomright'}});
legend.onAdd = function() {{
  var div = L.DomUtil.create('div', 'legend');
  div.innerHTML = `<b>Top operators</b><br>` +
    `<span class="sw" style="background:#0066cc"></span>PREPA<br>` +
    `<span class="sw" style="background:#660000"></span>DHS<br>` +
    `<span class="sw" style="background:#ff6600"></span>NOAA<br>` +
    `<span class="sw" style="background:#9933cc"></span>PR Admin Gen<br>` +
    `<span class="sw" style="background:#3399ff"></span>Blue Aviation<br>` +
    `<span class="sw" style="background:#cc6600"></span>Southwest Aviation<br>` +
    `<span class="sw" style="background:#cc0000"></span>USCG<br>` +
    `<span class="sw" style="background:#000099"></span>MASTER LINK CORP<br>` +
    `<span class="sw" style="background:#999999"></span>Private/Other<br>` +
    `<span class="sw" style="background:#ffffff;border:1px solid #ccc"></span>Unvisited municipality<br>` +
    `<br><i>Marker size ∝ sightings</i>`;
  return div;
}};
legend.addTo(map);
</script>
</body></html>"""
    (OUTS / "intel_spatial_map.html").write_text(html)

    conn.close()
    print(json.dumps({
        "pois_plotted":     len(plotted_pois),
        "pois_unvisited":   len(unvisited),
        "pr_municipalities_total": len(all_pr_munis),
        "outputs": [
            "outputs/intel_spatial_map.html",
            "outputs/intel_pois.geojson",
            "outputs/intel_pois_by_municipality.csv",
            "outputs/intel_coverage_gaps.csv",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
