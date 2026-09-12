#!/usr/bin/env python3
"""
Phase A: Spatial / geographic. Produces:

  - outputs/intel_spatial_map.html       self-contained interactive SVG showing
                                          every POI sized by sightings and
                                          colored by dominant operator
  - outputs/intel_pois.geojson           GeoJSON export for GIS applications
  - outputs/intel_pois_by_municipality.csv  per-municipality aircraft footprint
  - outputs/intel_coverage_gaps.csv      PR municipalities never observed

Uses lat/lon from data/places.geojson (TIGER 2025) + configs/georef_anchors.csv.

CLI:
    python3 scripts/rlsm_spatial_map.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _ascii_up(s: str) -> str:
    """Strip diacritics and uppercase: BAYAMÓN -> BAYAMON, AÑASCO -> ANASCO."""
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).upper().strip()


REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

# Color palette per dominant operator (cycle through these for less-common operators)
OPERATOR_COLORS = {
    "PREPA": "#0066cc",
    "Blue Aviation": "#3399ff",
    "Southwest Aviation": "#cc6600",
    "Private": "#999999",
    "Caribbean Helicopters": "#009933",
    "USCG": "#cc0000",
    "DEPARTMENT OF HOMELAND SECURITY": "#660000",
    "PUERTO RICO ELECTRIC POWER AUTHORITY": "#0066cc",
    "ADMINISTRACION DE SERVICIOS GENERALES": "#9933cc",
    "MASTER LINK CORP": "#000099",
    "UNITED STATES DEPARTMENT OF COMMERCE": "#ff6600",
}
FALLBACK_PALETTE = [
    "#7f7f7f",
    "#e377c2",
    "#bcbd22",
    "#17becf",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
]


def color_for(operator: str, palette_idx: list[int]) -> str:
    if operator in OPERATOR_COLORS:
        return OPERATOR_COLORS[operator]
    idx = palette_idx[0] % len(FALLBACK_PALETTE)
    palette_idx[0] += 1
    return FALLBACK_PALETTE[idx]


def _json_for_inline_script(value: Any) -> str:
    """Encode JSON without permitting data to terminate the script element."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_spatial_html(
    plotted_pois: list[dict[str, Any]],
    unvisited: list[str],
    poi_geo: dict[str, tuple[float, float, str]],
) -> str:
    """Render a single-file, network-free coordinate view.

    This deliberately avoids remote executable libraries and tile requests. The
    companion GeoJSON remains the canonical input for GIS/basemap workflows.
    """
    palette_idx = [0]
    markers = []
    for poi in plotted_pois:
        markers.append(
            {
                "name": poi["name"],
                "lat": poi["lat"],
                "lon": poi["lon"],
                "type": poi["type"],
                "sightings": poi["sightings"],
                "top_operator": poi["top_operator"],
                "top_aircraft": poi["top_aircraft"],
                "n_aircraft": poi["n_aircraft"],
                "radius": max(3, min(20, 3 + math.log1p(poi["sightings"]) * 2.5)),
                "color": color_for(poi["top_operator"], palette_idx),
            }
        )
    gaps = [
        {"name": municipality, "lat": poi_geo[municipality][0], "lon": poi_geo[municipality][1]}
        for municipality in unvisited[:200]
    ]
    marker_json = _json_for_inline_script(markers)
    gap_json = _json_for_inline_script(gaps)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<title>RLSM PR Operations Map</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{{color-scheme:light dark;font-family:system-ui,-apple-system,sans-serif}}
  body{{margin:0;background:#111827;color:#e5e7eb}}
  header{{padding:12px 18px;border-bottom:1px solid #374151}}
  h1{{font-size:18px;margin:0 0 4px}}
  .note{{font-size:12px;color:#9ca3af}}
  .layout{{display:grid;grid-template-columns:minmax(0,1fr) 320px;min-height:calc(100vh - 76px)}}
  #map{{width:100%;height:calc(100vh - 76px);background:#0f172a}}
  aside{{padding:14px;border-left:1px solid #374151;overflow:auto}}
  #detail{{white-space:pre-wrap;line-height:1.45;font-size:13px}}
  .legend{{font-size:12px;line-height:1.8;margin-top:18px}}
  .sw{{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-1px;margin-right:6px}}
  .axis-label{{font-size:11px;fill:#94a3b8}}
  .node-label{{font-size:10px;fill:#e5e7eb;pointer-events:none}}
  .poi{{cursor:pointer;stroke:#f8fafc;stroke-width:.7}}
  .poi:focus{{outline:none;stroke:#facc15;stroke-width:3}}
  .gap{{fill:#f8fafc;fill-opacity:.08;stroke:#94a3b8;stroke-width:1}}
  @media(max-width:850px){{.layout{{grid-template-columns:1fr}}aside{{border-left:0;border-top:1px solid #374151}}#map{{height:65vh}}}}
</style>
</head><body>
<header>
  <h1>RLSM Puerto Rico operations map — {len(markers)} POIs, {len(unvisited)} unvisited municipalities</h1>
  <div class="note">Self-contained coordinate view. No CDN, remote script, font, or basemap request. Use the companion GeoJSON for authoritative GIS context.</div>
</header>
<div class="layout">
  <svg id="map" viewBox="0 0 1200 760" role="img" aria-label="Puerto Rico aircraft observation coordinate map"></svg>
  <aside>
    <h2>Selected feature</h2>
    <div id="detail">Select or focus a marker. Marker size is proportional to sightings.</div>
    <div class="legend"><b>Top operators</b><br>
      <span class="sw" style="background:#0066cc"></span>PREPA<br>
      <span class="sw" style="background:#660000"></span>DHS<br>
      <span class="sw" style="background:#ff6600"></span>NOAA<br>
      <span class="sw" style="background:#9933cc"></span>PR Admin Gen<br>
      <span class="sw" style="background:#3399ff"></span>Blue Aviation<br>
      <span class="sw" style="background:#cc6600"></span>Southwest Aviation<br>
      <span class="sw" style="background:#cc0000"></span>USCG<br>
      <span class="sw" style="background:#000099"></span>MASTER LINK CORP<br>
      <span class="sw" style="background:#999999"></span>Private/Other<br>
      <span class="sw" style="background:#0f172a;border:1px solid #94a3b8"></span>Unvisited municipality
    </div>
  </aside>
</div>
<script>
"use strict";
const markers = {marker_json};
const gaps = {gap_json};
const svg = document.getElementById("map");
const detail = document.getElementById("detail");
const NS = "http://www.w3.org/2000/svg";
const width = 1200, height = 760, pad = 55;
const all = markers.concat(gaps);
const lons = all.map((point) => Number(point.lon));
const lats = all.map((point) => Number(point.lat));
let minLon = lons.length ? Math.min(...lons) : -67.4;
let maxLon = lons.length ? Math.max(...lons) : -65.2;
let minLat = lats.length ? Math.min(...lats) : 17.8;
let maxLat = lats.length ? Math.max(...lats) : 18.6;
const lonMargin = Math.max((maxLon - minLon) * 0.08, 0.05);
const latMargin = Math.max((maxLat - minLat) * 0.08, 0.03);
minLon -= lonMargin; maxLon += lonMargin; minLat -= latMargin; maxLat += latMargin;
function element(name, attrs = {{}}) {{
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}}
function project(point) {{
  return [
    pad + ((Number(point.lon) - minLon) / (maxLon - minLon || 1)) * (width - 2 * pad),
    height - pad - ((Number(point.lat) - minLat) / (maxLat - minLat || 1)) * (height - 2 * pad),
  ];
}}
const frame = element("rect", {{x:pad,y:pad,width:width-2*pad,height:height-2*pad,fill:"none",stroke:"#475569"}});
svg.append(frame);
for (let index = 0; index <= 5; index += 1) {{
  const x = pad + index * (width - 2 * pad) / 5;
  const y = pad + index * (height - 2 * pad) / 5;
  svg.append(element("line", {{x1:x,y1:pad,x2:x,y2:height-pad,stroke:"#1e293b"}}));
  svg.append(element("line", {{x1:pad,y1:y,x2:width-pad,y2:y,stroke:"#1e293b"}}));
  const lonLabel = element("text", {{x:x,y:height-pad+22,"text-anchor":"middle",class:"axis-label"}});
  lonLabel.textContent = (minLon + index * (maxLon - minLon) / 5).toFixed(3) + "°";
  svg.append(lonLabel);
  const latLabel = element("text", {{x:pad-8,y:y+4,"text-anchor":"end",class:"axis-label"}});
  latLabel.textContent = (maxLat - index * (maxLat - minLat) / 5).toFixed(3) + "°";
  svg.append(latLabel);
}}
for (const gap of gaps) {{
  const [x,y] = project(gap);
  const circle = element("circle", {{cx:x,cy:y,r:3,class:"gap"}});
  const title = element("title"); title.textContent = "UNVISITED: " + gap.name; circle.append(title);
  svg.append(circle);
}}
function describe(point) {{
  return [
    point.name,
    "Type: " + point.type,
    "Sightings: " + point.sightings,
    "Top operator: " + point.top_operator,
    "Top aircraft: " + (point.top_aircraft || "—"),
    "Unique aircraft: " + point.n_aircraft,
    "Coordinates: " + Number(point.lat).toFixed(6) + ", " + Number(point.lon).toFixed(6),
  ].join("\\n");
}}
for (const point of markers) {{
  const [x,y] = project(point);
  const circle = element("circle", {{
    cx:x,cy:y,r:point.radius,fill:point.color,"fill-opacity":0.68,class:"poi",tabindex:0,
    role:"button","aria-label":point.name,
  }});
  const title = element("title"); title.textContent = describe(point); circle.append(title);
  const select = () => {{ detail.textContent = describe(point); }};
  circle.addEventListener("click", select);
  circle.addEventListener("focus", select);
  svg.append(circle);
  if (Number(point.radius) >= 8) {{
    const label = element("text", {{x:x+Number(point.radius)+3,y:y+3,class:"node-label"}});
    label.textContent = point.name; svg.append(label);
  }}
}}
</script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    conn = sqlite3.connect(DB)

    # Load POI lat/lon from places.geojson + georef_anchors.
    poi_geo: dict[str, tuple[float, float, str]] = {}
    geojson = json.load((REPO / "data" / "places.geojson").open())
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        name = (props.get("NAME") or "").upper().strip()
        ascii_name = _ascii_up(name)
        try:
            lat = float(props.get("INTPTLAT") or 0)
            lon = float(props.get("INTPTLON") or 0)
        except (TypeError, ValueError):
            lat = lon = 0
        if name and lat and lon:
            poi_geo[name] = (lat, lon, "municipality")
            if ascii_name and ascii_name != name:
                poi_geo[ascii_name] = (lat, lon, "municipality")
    anchors_csv = REPO / "configs" / "georef_anchors.csv"
    if anchors_csv.exists():
        for row in csv.DictReader(anchors_csv.open()):
            for key in (row.get("anchor_id", ""), row.get("name", "")):
                normalized_key = key.upper().strip()
                try:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                    if normalized_key and lat and lon:
                        poi_geo.setdefault(
                            normalized_key, (lat, lon, "airport_or_anchor")
                        )
                except (KeyError, TypeError, ValueError):
                    pass

    poi_data = defaultdict(
        lambda: {"sightings": 0, "aircraft": Counter(), "operators": Counter()}
    )
    for row in conn.execute(
        """
        SELECT lp.normalized_label, a.registration, a.operator_text_manual
        FROM labeled_pins lp
        JOIN aircraft_observations a ON a.screenshot_id = lp.screenshot_id
        WHERE lp.pin_type_guess != 'unknown_label_candidate'
        """
    ):
        normalized, registration, operator = row
        data = poi_data[_ascii_up(normalized)]
        data["sightings"] += 1
        if registration:
            data["aircraft"][registration] += 1
        if operator:
            data["operators"][operator] += 1

    plotted_pois = []
    for normalized, info in poi_data.items():
        lookup = normalized if normalized in poi_geo else _ascii_up(normalized)
        if lookup not in poi_geo:
            continue
        lat, lon, place_type = poi_geo[lookup]
        top_operator = (
            info["operators"].most_common(1)[0][0] if info["operators"] else "?"
        )
        top_aircraft = ", ".join(
            f"{registration}({count})"
            for registration, count in info["aircraft"].most_common(3)
        )
        plotted_pois.append(
            {
                "name": normalized,
                "lat": lat,
                "lon": lon,
                "type": place_type,
                "sightings": info["sightings"],
                "top_operator": top_operator,
                "top_aircraft": top_aircraft,
                "n_aircraft": len(info["aircraft"]),
            }
        )

    palette_idx = [0]
    features = []
    for poi in plotted_pois:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [poi["lon"], poi["lat"]],
                },
                "properties": {
                    "name": poi["name"],
                    "type": poi["type"],
                    "sightings": poi["sightings"],
                    "top_operator": poi["top_operator"],
                    "top_aircraft": poi["top_aircraft"],
                    "n_unique_aircraft": poi["n_aircraft"],
                    "marker_color": color_for(poi["top_operator"], palette_idx),
                },
            }
        )
    OUTS.mkdir(parents=True, exist_ok=True)
    (OUTS / "intel_pois.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )

    all_pr_munis_ascii = {
        _ascii_up(name)
        for name, info in poi_geo.items()
        if info[2] == "municipality"
    }
    visited_munis_ascii = {
        _ascii_up(poi["name"])
        for poi in plotted_pois
        if poi["type"] == "municipality"
    }
    unvisited_ascii = sorted(all_pr_munis_ascii - visited_munis_ascii)
    ascii_to_display = {}
    for name, info in poi_geo.items():
        if info[2] == "municipality":
            ascii_to_display.setdefault(_ascii_up(name), name)
    unvisited = [
        ascii_to_display[name] for name in unvisited_ascii if name in ascii_to_display
    ]

    with (OUTS / "intel_pois_by_municipality.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            [
                "name",
                "lat",
                "lon",
                "sightings",
                "n_unique_aircraft",
                "top_operator",
                "top_aircraft",
            ]
        )
        for poi in sorted(plotted_pois, key=lambda item: -item["sightings"]):
            if poi["type"] != "municipality":
                continue
            writer.writerow(
                [
                    poi["name"],
                    poi["lat"],
                    poi["lon"],
                    poi["sightings"],
                    poi["n_aircraft"],
                    poi["top_operator"],
                    poi["top_aircraft"],
                ]
            )

    with (OUTS / "intel_coverage_gaps.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["municipality", "lat", "lon"])
        for municipality in unvisited:
            lat, lon, _ = poi_geo[municipality]
            writer.writerow([municipality, lat, lon])

    (OUTS / "intel_spatial_map.html").write_text(
        render_spatial_html(plotted_pois, unvisited, poi_geo), encoding="utf-8"
    )

    conn.close()
    print(
        json.dumps(
            {
                "pois_plotted": len(plotted_pois),
                "pois_unvisited": len(unvisited),
                "pr_municipalities_total": len(all_pr_munis_ascii),
                "outputs": [
                    "outputs/intel_spatial_map.html",
                    "outputs/intel_pois.geojson",
                    "outputs/intel_pois_by_municipality.csv",
                    "outputs/intel_coverage_gaps.csv",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
