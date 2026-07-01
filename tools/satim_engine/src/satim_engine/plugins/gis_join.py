from __future__ import annotations
import pandas as pd

def bbox_context_join(track_df: pd.DataFrame, layers: dict | None = None) -> pd.DataFrame:
    """Safe GIS join plugin stub.
    Production replacement can use geopandas/rtree feature intersections.
    This default emits bbox-context rows and never mutates input.
    """
    if track_df.empty:
        return pd.DataFrame(columns=["source","latitude","longitude","gis_join_status"])
    out = track_df[["source","latitude","longitude"]].copy()
    out["gis_join_status"] = "BBOX_CONTEXT_ONLY"
    out["gis_layer_count"] = 0 if layers is None else len(layers)
    return out
