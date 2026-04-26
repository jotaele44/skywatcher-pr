"""
Corridor builder for GEO-PR-INT.

Aggregates per-candidate data into corridor-level records:
centroid, bounding box, dominant infra type, mean/max score,
total contract value.

Outputs GeoJSON LineString features connecting corridor endpoints.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from config import GEO_PR_INT_ROOT, SETTINGS
from utils.geo_helpers import linearity_r2, corridor_bearing_deg

logger = logging.getLogger(__name__)

_OUTPUT = SETTINGS["output"]
_GJ_DIR = GEO_PR_INT_ROOT / _OUTPUT.get("geojson_dir", "outputs/geojson")


@dataclass
class CorridorRecord:
    corridor_id:              int
    linearity_r2:             float
    bearing_deg:              float
    n_points:                 int
    centroid_lat:             float
    centroid_lon:             float
    bbox_wkt:                 str
    dominant_infra_type:      str
    mean_score:               float
    max_score:                float
    total_obligated_amount:   float
    matched_contract_count:   int
    representative_candidates: list = field(default_factory=list)


def _bbox_wkt(lats: np.ndarray, lons: np.ndarray) -> str:
    """Return a WKT POLYGON bounding box string."""
    min_lat, max_lat = float(lats.min()), float(lats.max())
    min_lon, max_lon = float(lons.min()), float(lons.max())
    return (
        f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    )


def _dominant_value(series: pd.Series, default: str = "unknown") -> str:
    """Return mode of a string Series, fallback to default."""
    try:
        counts = series.dropna().value_counts()
        if len(counts):
            return str(counts.index[0])
    except Exception:
        pass
    return default


def build_corridors(df: pd.DataFrame) -> list[CorridorRecord]:
    """
    Build CorridorRecord list from scored candidates.

    Uses corridor_id column (0 = non-corridor/noise, skipped).
    Sorted by mean_score descending.
    """
    if df.empty or "corridor_id" not in df.columns:
        return []

    records: list[CorridorRecord] = []
    score_col = "unified_score" if "unified_score" in df.columns else "composite_score"

    for cid, group in df[df["corridor_id"] > 0].groupby("corridor_id"):
        lats = group["lat"].values.astype(float)
        lons = group["lon"].values.astype(float)

        scores = pd.to_numeric(group.get(score_col, pd.Series(0, index=group.index)), errors="coerce").fillna(0.0)

        # Top-3 representative candidates (highest score)
        top3 = (
            group.nlargest(3, score_col) if score_col in group.columns
            else group.head(3)
        )
        rep = top3[["lat", "lon", score_col]].to_dict(orient="records") if not top3.empty else []

        rec = CorridorRecord(
            corridor_id              = int(cid),
            linearity_r2             = float(group["linearity_r2"].iloc[0]) if "linearity_r2" in group.columns else linearity_r2(lats, lons),
            bearing_deg              = float(group["bearing_deg"].iloc[0])  if "bearing_deg"  in group.columns else corridor_bearing_deg(lats, lons),
            n_points                 = len(group),
            centroid_lat             = float(lats.mean()),
            centroid_lon             = float(lons.mean()),
            bbox_wkt                 = _bbox_wkt(lats, lons),
            dominant_infra_type      = _dominant_value(group.get("infra_type", pd.Series())),
            mean_score               = float(scores.mean()),
            max_score                = float(scores.max()),
            total_obligated_amount   = float(pd.to_numeric(group.get("total_obligated_amount", 0), errors="coerce").fillna(0).sum()),
            matched_contract_count   = int(pd.to_numeric(group.get("matched_contract_count", 0), errors="coerce").fillna(0).sum()),
            representative_candidates = rep,
        )
        records.append(rec)

    records.sort(key=lambda r: r.mean_score, reverse=True)
    logger.info(f"CorridorBuilder: {len(records)} corridors built")
    return records


def corridors_to_dataframe(corridors: list[CorridorRecord]) -> pd.DataFrame:
    """Flatten CorridorRecord list to a DataFrame (excluding representative_candidates)."""
    if not corridors:
        return pd.DataFrame()
    rows = []
    for c in corridors:
        d = asdict(c)
        d.pop("representative_candidates", None)
        rows.append(d)
    return pd.DataFrame(rows)


def corridors_to_geojson(
    corridors: list[CorridorRecord],
    candidates_df: pd.DataFrame,
    output_path: Path | None = None,
) -> dict:
    """
    Build a GeoJSON FeatureCollection of corridor LineStrings.

    Each LineString connects candidate points belonging to the corridor,
    sorted by latitude (south → north).
    """
    features = []
    for corridor in corridors:
        cid = corridor.corridor_id
        if "corridor_id" in candidates_df.columns:
            members = candidates_df[candidates_df["corridor_id"] == cid]
        else:
            members = pd.DataFrame()

        if len(members) >= 2:
            sorted_m = members.sort_values("lat")
            coords = [[float(r["lon"]), float(r["lat"])] for _, r in sorted_m.iterrows()]
            geom_type = "LineString"
            geometry = {"type": geom_type, "coordinates": coords}
        else:
            geometry = {
                "type": "Point",
                "coordinates": [corridor.centroid_lon, corridor.centroid_lat],
            }

        props = {k: v for k, v in asdict(corridor).items()
                 if k not in ("representative_candidates", "bbox_wkt")}
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": props,
        })

    fc = {"type": "FeatureCollection", "features": features}

    if output_path is None:
        output_path = _GJ_DIR / "corridors.geojson"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, indent=2)
    logger.info(f"Corridors GeoJSON: {len(features)} features → {output_path}")
    return fc
