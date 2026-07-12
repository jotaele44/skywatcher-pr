"""SATIM GIS join plugin.

Offline-computable spatial context join for SATIM track ledgers.

Two operating modes, selected purely by what the caller supplies — no network,
no GDAL/GeoPandas dependency:

* **Context-only** (default): when ``layers`` is ``None`` or carries no
  recognizable geometry, every row is stamped ``BBOX_CONTEXT_ONLY``. This is the
  original safe behavior and never mutates the input frame.
* **Offline geometric join**: when ``layers`` supplies bounding boxes (see
  :func:`satim_engine.plugins.gis_geometry.layer_bbox`), each track point is
  tested against every layer's bbox with pure planar arithmetic. Rows gain
  ``GIS_JOIN_OFFLINE`` status plus the matched layer names and the nearest layer
  distance in degrees.

Production replacement can swap the geometry backend for geopandas/rtree feature
intersections (polygon containment, projected distances). The pure helpers in
``gis_geometry`` are the stable, dependency-free contract such a backend must
preserve, and they are unit-testable without pandas.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .gis_geometry import (
    as_float,
    bbox_distance_deg,
    point_in_bbox,
    resolve_geometry_layers,
)

CONTEXT_ONLY_STATUS = "BBOX_CONTEXT_ONLY"
OFFLINE_JOIN_STATUS = "GIS_JOIN_OFFLINE"


def bbox_context_join(track_df: pd.DataFrame, layers: dict | None = None) -> pd.DataFrame:
    """Attach GIS context to a SATIM track ledger.

    Never mutates *track_df*. Emits at minimum the columns required by the
    ``SATIM_GIS_JOIN_LEDGER.csv`` schema
    (``source``, ``latitude``, ``longitude``, ``gis_join_status``); when the
    frame is non-empty it also emits ``gis_layer_count``. When *layers* carry
    recognizable geometry, two further columns are added:
    ``gis_matched_layers`` (``|``-joined names, empty string when none) and
    ``gis_nearest_layer_deg`` (planar degrees to the closest layer).
    """
    if track_df.empty:
        # Preserve the historical empty-frame contract exactly.
        return pd.DataFrame(columns=["source", "latitude", "longitude", "gis_join_status"])

    out = track_df[["source", "latitude", "longitude"]].copy()
    out["gis_layer_count"] = 0 if layers is None else len(layers)

    geom_layers = resolve_geometry_layers(layers)
    if not geom_layers:
        # Context-only: no usable geometry (or opaque layer handles).
        out["gis_join_status"] = CONTEXT_ONLY_STATUS
        return out

    statuses: list[str] = []
    matched_col: list[str] = []
    nearest_col: list[Optional[float]] = []
    for lat, lon in zip(out["latitude"], out["longitude"]):
        flat, flon = as_float(lat), as_float(lon)
        if flat is None or flon is None:
            # A track point with no usable coordinate cannot be joined.
            statuses.append(CONTEXT_ONLY_STATUS)
            matched_col.append("")
            nearest_col.append(None)
            continue
        matched = [name for name, bbox in geom_layers if point_in_bbox(flat, flon, bbox)]
        nearest = min(bbox_distance_deg(flat, flon, bbox) for _, bbox in geom_layers)
        statuses.append(OFFLINE_JOIN_STATUS)
        matched_col.append("|".join(sorted(matched)))
        nearest_col.append(round(nearest, 6))

    out["gis_join_status"] = statuses
    out["gis_matched_layers"] = matched_col
    out["gis_nearest_layer_deg"] = nearest_col
    return out
