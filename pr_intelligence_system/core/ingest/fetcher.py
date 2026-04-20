import glob
import logging
import os

import geopandas as gpd

logger = logging.getLogger(__name__)


def fetch_for_aoi(
    aoi_gdf: gpd.GeoDataFrame,
    aoi_id: str,
    output_dir: str,
    days_back: int = 90,
) -> list:
    """
    Fetch Sentinel-2 NDVI and Copernicus DEM for a given AOI via openEO.

    Both datasets are downloaded to output_dir with type-prefixed filenames:
      ndvi_<filename>.tif  — Sentinel-2 NDVI (optical, 10m)
      dem_<filename>.tif   — Copernicus GLO-30 DEM (terrain, 30m)

    If files already exist for both types, they are returned immediately
    without re-fetching (cache-aware).

    DEM fetch is non-fatal: if it fails, only NDVI paths are returned and
    aoi_pipeline will fall back to synthetic elevation.

    Parameters
    ----------
    aoi_gdf    : single-row GeoDataFrame of the AOI polygon (EPSG:4326)
    aoi_id     : 8-char hex identifier (used for filenames and job titles)
    output_dir : directory where GeoTIFFs are saved (created if absent)
    days_back  : temporal window in days for Sentinel-2 search

    Returns
    -------
    list of absolute paths to downloaded GeoTIFF files (may be empty on failure)
    """
    from core.ingest.loaders.openeo_loader import (
        build_bbox,
        build_temporal_extent,
        connect,
        fetch_dem,
        fetch_sentinel2,
    )

    os.makedirs(output_dir, exist_ok=True)

    existing_ndvi = glob.glob(os.path.join(output_dir, "ndvi_*.tif"))
    existing_dem = glob.glob(os.path.join(output_dir, "dem_*.tif"))

    if existing_ndvi and existing_dem:
        logger.info(
            "All satellite data cached for AOI %s (%d NDVI, %d DEM); skipping fetch.",
            aoi_id, len(existing_ndvi), len(existing_dem),
        )
        return existing_ndvi + existing_dem

    try:
        connection = connect()
        bbox = build_bbox(aoi_gdf)
    except (ConnectionError, ImportError) as exc:
        logger.error("Satellite fetch failed (auth/connectivity): %s", exc)
        raise

    all_paths = []

    # --- Sentinel-2 NDVI ---
    if existing_ndvi:
        logger.info("NDVI already cached for AOI %s; skipping S2 fetch.", aoi_id)
        all_paths.extend(existing_ndvi)
    else:
        try:
            temporal_extent = build_temporal_extent(days_back)
            ndvi_paths = fetch_sentinel2(connection, bbox, temporal_extent, output_dir, aoi_id)
            if not ndvi_paths:
                logger.warning(
                    "Sentinel-2 returned no data for AOI %s "
                    "(check cloud cover or temporal window).",
                    aoi_id,
                )
            all_paths.extend(ndvi_paths)
        except Exception as exc:
            logger.error("Sentinel-2 fetch failed for AOI %s: %s", aoi_id, exc)

    # --- Copernicus DEM (non-fatal) ---
    if existing_dem:
        logger.info("DEM already cached for AOI %s; skipping DEM fetch.", aoi_id)
        all_paths.extend(existing_dem)
    else:
        try:
            dem_paths = fetch_dem(connection, bbox, output_dir, aoi_id)
            if dem_paths:
                logger.info("DEM fetched: %d file(s).", len(dem_paths))
                all_paths.extend(dem_paths)
            else:
                logger.warning("DEM returned no data for AOI %s; elevation will be synthetic.", aoi_id)
        except Exception as exc:
            logger.warning(
                "DEM fetch failed for AOI %s (%s); elevation will be synthetic.",
                aoi_id, exc,
            )

    return all_paths
