"""GeoJSON exports for direct-coordinate GATIM rows."""
from __future__ import annotations

import json
from pathlib import Path

GEOJSON_PROPERTIES = [
    "gatim_id",
    "source_dataset",
    "class_primary",
    "review_priority",
    "confidence",
    "coord_status",
    "grid_id",
    "evidence_tier",
    "visual_features",
]


def feature_for(row) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(row.lon), float(row.lat)]},
        "properties": {key: str(getattr(row, key, "")) for key in GEOJSON_PROPERTIES},
    }


def as_feature_collection(rows: list) -> dict:
    features = []
    for row in rows:
        if row.coord_status != "direct":
            continue
        try:
            float(row.lat)
            float(row.lon)
        except (TypeError, ValueError):
            continue
        features.append(feature_for(row))
    return {"type": "FeatureCollection", "features": features}


def write_geojson(rows: list, output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(as_feature_collection(rows), indent=2), encoding="utf-8")
