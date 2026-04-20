import hashlib
import logging
import os
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

CRS_WGS84 = "EPSG:4326"
MEMORY_LAYER = "spatial_memory"

_SCHEMA_COLUMNS = [
    "aoi_id",
    "geometry",
    "timestamp",
    "ilap_count",
    "mean_confidence",
    "corridor_count",
    "result_path",
    "status",
]


def generate_aoi_id(lat: float, lon: float, radius_km: float) -> str:
    """Deterministic 8-char hex AOI identifier based on rounded coordinates."""
    key = f"{round(lat, 3)}_{round(lon, 3)}_{radius_km}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _empty_memory() -> gpd.GeoDataFrame:
    df = pd.DataFrame(columns=_SCHEMA_COLUMNS)
    return gpd.GeoDataFrame(df, geometry="geometry", crs=CRS_WGS84)


def load_memory(memory_path: str) -> gpd.GeoDataFrame:
    """Load the spatial memory GeoPackage; return empty GDF if absent."""
    if not os.path.exists(memory_path):
        logger.info("No memory store found at %s, starting fresh.", memory_path)
        return _empty_memory()

    try:
        gdf = gpd.read_file(memory_path, layer=MEMORY_LAYER)
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(CRS_WGS84)
        logger.info("Loaded %d record(s) from spatial memory.", len(gdf))
        return gdf
    except Exception as exc:
        logger.warning("Could not read memory store (%s); returning empty.", exc)
        return _empty_memory()


def check_coverage(
    aoi_gdf: gpd.GeoDataFrame,
    memory_gdf: gpd.GeoDataFrame,
) -> tuple:
    """
    Determine coverage status of the query AOI against stored memory.

    Returns
    -------
    (status, matching_records)
      status : "new" | "partial" | "full"
      matching_records : GeoDataFrame of intersecting memory rows
    """
    if memory_gdf is None or memory_gdf.empty:
        return "new", _empty_memory()

    if "geometry" not in memory_gdf.columns:
        return "new", _empty_memory()

    if memory_gdf.crs != aoi_gdf.crs:
        memory_gdf = memory_gdf.to_crs(aoi_gdf.crs)

    try:
        intersecting = gpd.sjoin(
            memory_gdf,
            aoi_gdf[["geometry"]],
            how="inner",
            predicate="intersects",
        )
        intersecting = intersecting.drop(
            columns=[c for c in intersecting.columns if c.startswith("index_")],
            errors="ignore",
        )
    except Exception as exc:
        logger.warning("Spatial join failed (%s); treating as new AOI.", exc)
        return "new", _empty_memory()

    if intersecting.empty:
        return "new", _empty_memory()

    stored_union = unary_union(intersecting.geometry)
    query_polygon = aoi_gdf.geometry.iloc[0]

    if stored_union.contains(query_polygon):
        logger.info("Coverage: FULL — returning cached result.")
        return "full", intersecting
    else:
        logger.info("Coverage: PARTIAL — %d overlapping record(s).", len(intersecting))
        return "partial", intersecting


def save_to_memory(
    memory_path: str,
    aoi_id: str,
    aoi_gdf: gpd.GeoDataFrame,
    summary: dict,
    result_path: str,
    status: str = "complete",
) -> None:
    """Append a new record to the spatial memory GeoPackage."""
    new_record = gpd.GeoDataFrame(
        {
            "aoi_id": [aoi_id],
            "timestamp": [datetime.now(timezone.utc).isoformat()],
            "ilap_count": [summary.get("total_ilaps", 0)],
            "mean_confidence": [summary.get("mean_confidence", 0.0)],
            "corridor_count": [summary.get("corridor_count", 0)],
            "result_path": [result_path],
            "status": [status],
        },
        geometry=aoi_gdf.geometry.values,
        crs=CRS_WGS84,
    )

    try:
        os.makedirs(os.path.dirname(memory_path), exist_ok=True)

        if os.path.exists(memory_path):
            existing = load_memory(memory_path)
            combined = pd.concat([existing, new_record], ignore_index=True)
            combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=CRS_WGS84)
        else:
            combined = new_record

        combined.to_file(memory_path, layer=MEMORY_LAYER, driver="GPKG")
        logger.info("Saved AOI %s to memory store (%s).", aoi_id, status)
    except Exception as exc:
        logger.error("Failed to save to memory store: %s", exc)
        raise
