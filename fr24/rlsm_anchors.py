"""Per-screenshot calibration anchors from the RLSM store.

Collects (pixel_x, pixel_y, lat, lon) anchors for a screenshot from the two
places the RLSM pipeline records them:

  1. geo_anchors rows that carry both a pixel position and a geo position.
  2. labeled_pins rows whose word-level centroid has been backfilled
     (scripts/rlsm_reocr_label_layer.py — the original extractor stores NULL
     centroids) and whose normalized label vocab-matches a known place from
     data/places.geojson or a named geo_anchors row.

The result feeds GeoCalibration(mode="per_screenshot_affine", anchors=...)
(integration/geo_calibration.py) and scripts/sync_rlsm_calibration.py.
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
PLACES_GEOJSON = REPO / "data" / "places.geojson"

# (pixel_x, pixel_y, lat, lon)
Anchor = Tuple[float, float, float, float]


def ascii_upper(s: str) -> str:
    """Accent-stripped upper-case key ('Añasco' -> 'ANASCO')."""
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).upper().strip()


def build_geo_lookup(conn: sqlite3.Connection,
                     places_geojson: Optional[Path] = None) -> Dict[str, Tuple[float, float]]:
    """Name -> (lat, lon) vocabulary from places.geojson + named geo_anchors.

    places.geojson is operator-local (not tracked); a missing file just means
    the lookup is built from geo_anchors alone.
    """
    lookup: Dict[str, Tuple[float, float]] = {}
    path = places_geojson if places_geojson is not None else PLACES_GEOJSON
    if path and Path(path).exists():
        gj = json.loads(Path(path).read_text())
        for feature in gj.get("features", []):
            props = feature.get("properties", {})
            name = (props.get("NAME") or "").upper().strip()
            try:
                lat = float(props.get("INTPTLAT") or 0)
                lon = float(props.get("INTPTLON") or 0)
            except (TypeError, ValueError):
                continue
            if name and lat and lon:
                lookup[ascii_upper(name)] = (lat, lon)
    for name, lat, lon in conn.execute(
        "SELECT name, lat, lon FROM geo_anchors"
        " WHERE name IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL"
    ):
        lookup[ascii_upper(name)] = (float(lat), float(lon))
    return lookup


def anchors_for_screenshot(conn: sqlite3.Connection,
                           screenshot_id: int,
                           geo_lookup: Optional[Dict[str, Tuple[float, float]]] = None,
                           ) -> List[Anchor]:
    """All usable calibration anchors for one screenshot, pixel-deduplicated."""
    if geo_lookup is None:
        geo_lookup = build_geo_lookup(conn)

    anchors: List[Anchor] = []
    for px, py, lat, lon in conn.execute(
        "SELECT pixel_x, pixel_y, lat, lon FROM geo_anchors"
        " WHERE screenshot_id = ? AND pixel_x IS NOT NULL AND pixel_y IS NOT NULL"
        " AND lat IS NOT NULL AND lon IS NOT NULL",
        (screenshot_id,),
    ):
        anchors.append((float(px), float(py), float(lat), float(lon)))

    for label, cx, cy in conn.execute(
        "SELECT normalized_label, centroid_x, centroid_y FROM labeled_pins"
        " WHERE screenshot_id = ? AND centroid_x IS NOT NULL AND centroid_y IS NOT NULL"
        " AND pin_type_guess != 'unknown_label_candidate'",
        (screenshot_id,),
    ):
        latlon = geo_lookup.get(ascii_upper(label or ""))
        if latlon and cx and cy:
            anchors.append((float(cx), float(cy), latlon[0], latlon[1]))

    seen = set()
    deduped: List[Anchor] = []
    for anchor in anchors:
        key = (round(anchor[0], 1), round(anchor[1], 1))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(anchor)
    return deduped
