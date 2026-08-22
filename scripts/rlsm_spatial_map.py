#!/usr/bin/env python3
"""Legacy screen-label spatial aggregation — NONCANONICAL/AUDIT_ONLY.

This historical visualization joins labeled map POIs to aircraft merely because
both appear in the same screenshot. Map-label visibility is not aircraft
position, municipal footprint, destination, or operational relation. The
calculation is retained only with ``--audit-only`` and writes quarantined
artifacts.
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

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

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


def _ascii_up(value: str) -> str:
    if not value:
        return ""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    ).upper().strip()


def color_for(operator: str, palette_idx: list[int]) -> str:
    if operator in OPERATOR_COLORS:
        return OPERATOR_COLORS[operator]
    index = palette_idx[0] % len(FALLBACK_PALETTE)
    palette_idx[0] += 1
    return FALLBACK_PALETTE[index]


def main() -> int:
    global OUTS
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = parser.parse_args()
    audit_dir = enter_audit_only(
        analysis="spatial_map", audit_only=args.audit_only, repo=REPO
    )
    if audit_dir is None:
        return 2
    OUTS = audit_dir

    conn = sqlite3.connect(DB)
    poi_geo = {}
    with (REPO / "data" / "places.geojson").open() as handle:
        places = json.load(handle)
    for feature in places.get("features", []):
        properties = feature.get("properties", {})
        name = (properties.get("NAME") or "").upper().strip()
        ascii_name = _ascii_up(name)
        try:
            lat = float(properties.get("INTPTLAT") or 0)
            lon = float(properties.get("INTPTLON") or 0)
        except (TypeError, ValueError):
            lat = lon = 0
        if name and lat and lon:
            poi_geo[name] = (lat, lon, "municipality")
            if ascii_name and ascii_name != name:
                poi_geo[ascii_name] = (lat, lon, "municipality")

    anchors_csv = REPO / "configs" / "georef_anchors.csv"
    if anchors_csv.exists():
        with anchors_csv.open() as handle:
            for row in csv.DictReader(handle):
                for raw_key in (row.get("anchor_id", ""), row.get("name", "")):
                    key = raw_key.upper().strip()
                    try:
                        lat = float(row["lat"])
                        lon = float(row["lon"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if key and lat and lon:
                        poi_geo.setdefault(key, (lat, lon, "airport_or_anchor"))

    poi_data = defaultdict(
        lambda: {"sightings": 0, "aircraft": Counter(), "operators": Counter()}
    )
    for normalized, registration, operator in conn.execute(
        """
        SELECT lp.normalized_label, a.registration, a.operator_text_manual
        FROM labeled_pins lp
        JOIN aircraft_observations a ON a.screenshot_id = lp.screenshot_id
        WHERE lp.pin_type_guess != 'unknown_label_candidate'
        """
    ):
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
        lat, lon, poi_type = poi_geo[lookup]
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
                "type": poi_type,
                "sightings": info["sightings"],
                "top_operator": top_operator,
                "top_aircraft": top_aircraft,
                "n_aircraft": len(info["aircraft"]),
                "spatial_state": "SCREEN_CONTEXT_ONLY",
                "certification_state": "AUDIT_ONLY",
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
                    "screen_context_count": poi["sightings"],
                    "top_operator": poi["top_operator"],
                    "top_aircraft": poi["top_aircraft"],
                    "n_unique_aircraft": poi["n_aircraft"],
                    "spatial_state": "SCREEN_CONTEXT_ONLY",
                    "certification_state": "AUDIT_ONLY",
                    "marker_color": color_for(poi["top_operator"], palette_idx),
                },
            }
        )
    OUTS.mkdir(parents=True, exist_ok=True)
    (OUTS / "audit_screen_context_pois.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    all_municipalities = {
        _ascii_up(name)
        for name, info in poi_geo.items()
        if info[2] == "municipality"
    }
    visible_municipalities = {
        _ascii_up(poi["name"])
        for poi in plotted_pois
        if poi["type"] == "municipality"
    }
    not_visible = sorted(all_municipalities - visible_municipalities)

    fields = [
        "name",
        "lat",
        "lon",
        "screen_context_count",
        "n_unique_aircraft",
        "top_operator",
        "top_aircraft",
        "spatial_state",
        "certification_state",
    ]
    with (OUTS / "audit_screen_context_by_municipality.csv").open(
        "w", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for poi in sorted(plotted_pois, key=lambda item: -item["sightings"]):
            if poi["type"] != "municipality":
                continue
            writer.writerow(
                {
                    "name": poi["name"],
                    "lat": poi["lat"],
                    "lon": poi["lon"],
                    "screen_context_count": poi["sightings"],
                    "n_unique_aircraft": poi["n_aircraft"],
                    "top_operator": poi["top_operator"],
                    "top_aircraft": poi["top_aircraft"],
                    "spatial_state": "SCREEN_CONTEXT_ONLY",
                    "certification_state": "AUDIT_ONLY",
                }
            )

    palette_idx = [0]
    marker_javascript = []
    for poi in plotted_pois:
        radius = max(3, min(20, 3 + math.log1p(poi["sightings"]) * 2.5))
        color = color_for(poi["top_operator"], palette_idx)
        popup = (
            f"<b>{poi['name']}</b><br>"
            f"NONCANONICAL screen context only<br>"
            f"Visible with aircraft rows: {poi['sightings']}<br>"
            f"Top operator string: {poi['top_operator']}<br>"
            f"Top aircraft strings: {poi['top_aircraft']}"
        ).replace('"', "&quot;")
        marker_javascript.append(
            f'L.circleMarker([{poi["lat"]}, {poi["lon"]}], '
            f'{{radius:{radius:.1f}, color:"{color}", fillColor:"{color}", '
            f'fillOpacity:0.6, weight:1}}).bindPopup("{popup}").addTo(map);'
        )

    html = f"""<!DOCTYPE html>
<html><head>
<title>RLSM NONCANONICAL screen-context map</title>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;font-family:sans-serif}}#map{{height:100vh;width:100%}}</style>
</head><body>
<div id="map"></div>
<script>
var map = L.map('map').setView([18.22, -66.59], 9);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom:18}}).addTo(map);
{chr(10).join(marker_javascript)}
</script>
</body></html>"""
    (OUTS / "audit_screen_context_map.html").write_text(html, encoding="utf-8")

    conn.close()
    result = {
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY",
        "spatial_state": "SCREEN_CONTEXT_ONLY",
        "pois_plotted": len(plotted_pois),
        "municipality_labels_not_visible": len(not_visible),
        "pr_municipality_reference_count": len(all_municipalities),
        "nonclaim": "label visibility is not aircraft position, visit, footprint, or coverage",
        "outputs": [
            str((OUTS / "audit_screen_context_map.html").relative_to(REPO)),
            str((OUTS / "audit_screen_context_pois.geojson").relative_to(REPO)),
            str((OUTS / "audit_screen_context_by_municipality.csv").relative_to(REPO)),
        ],
    }
    (OUTS / "audit_screen_context_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
