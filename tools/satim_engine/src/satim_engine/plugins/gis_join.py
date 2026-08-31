"""SATIM GIS join plugin.

Offline-computable spatial context join for SATIM track ledgers.

The legacy ``gis_nearest_layer_deg`` output remains for reproducibility, but
``gis_nearest_layer_m`` is the production proximity metric and is computed on
WGS84 geodesics. Context-only behavior remains fail-closed when no geometry is
available.
"""
from __future__ import annotations

import pandas as pd

from .gis_geometry import as_float, bbox_distance_deg, point_in_bbox, resolve_geometry_layers
from .gis_geodesic import bbox_distance_m

CONTEXT_ONLY_STATUS = "BBOX_CONTEXT_ONLY"
OFFLINE_JOIN_STATUS = "GIS_JOIN_OFFLINE_GEODESIC"


def bbox_context_join(track_df: pd.DataFrame, layers: dict | None = None) -> pd.DataFrame:
    if track_df.empty:
        return pd.DataFrame(columns=["source", "latitude", "longitude", "gis_join_status"])

    out = track_df[["source", "latitude", "longitude"]].copy()
    layer_count = 0 if layers is None else len(layers)
    geom_layers = resolve_geometry_layers(layers)
    if not geom_layers:
        out["gis_join_status"] = CONTEXT_ONLY_STATUS
        out["gis_layer_count"] = layer_count
        return out

    out["gis_layer_count"] = layer_count
    statuses: list[str] = []
    matched_col: list[str] = []
    nearest_deg_col: list[float | None] = []
    nearest_m_col: list[float | None] = []
    for lat, lon in zip(out["latitude"], out["longitude"], strict=True):
        flat, flon = as_float(lat), as_float(lon)
        if flat is None or flon is None:
            statuses.append(CONTEXT_ONLY_STATUS)
            matched_col.append("")
            nearest_deg_col.append(None)
            nearest_m_col.append(None)
            continue
        matched = [name for name, bbox in geom_layers if point_in_bbox(flat, flon, bbox)]
        nearest_deg = min(bbox_distance_deg(flat, flon, bbox) for _, bbox in geom_layers)
        nearest_m = min(bbox_distance_m(flat, flon, bbox) for _, bbox in geom_layers)
        statuses.append(OFFLINE_JOIN_STATUS)
        matched_col.append("|".join(sorted(matched)))
        nearest_deg_col.append(round(nearest_deg, 6))
        nearest_m_col.append(round(nearest_m, 3))

    out["gis_join_status"] = statuses
    out["gis_matched_layers"] = matched_col
    out["gis_nearest_layer_deg"] = nearest_deg_col
    out["gis_nearest_layer_m"] = nearest_m_col
    return out
