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
    include_sar: bool = False,
    cdse_username: str = None,
    cdse_password: str = None,
) -> list:
    """
    Fetch satellite data for an AOI via openEO (Sentinel-2 NDVI + DEM) and,
    optionally, via the Copernicus ODP API (Sentinel-1 SAR backscatter).

    Downloaded files use type-prefixed filenames:
      ndvi_*.tif  — Sentinel-2 NDVI (optical, 10 m)
      dem_*.tif   — Copernicus GLO-30 DEM (terrain, 30 m)
      sar_*.tif   — Sentinel-1 CARD-BS backscatter (SAR, 10 m)

    Existing prefixed files are reused without re-fetching (per-type cache).
    DEM and SAR fetches are non-fatal: failures are logged and skipped.

    Parameters
    ----------
    aoi_gdf       : single-row GeoDataFrame of the AOI polygon (EPSG:4326)
    aoi_id        : 8-char hex identifier (used for filenames and job labels)
    output_dir    : directory where GeoTIFFs are saved (created if absent)
    days_back     : temporal window in days for Sentinel-2 and SAR searches
    include_sar   : if True, also fetch Sentinel-1 CARD-BS via ODP
    cdse_username : Copernicus username for ODP auth (falls back to CDSE_USER env var)
    cdse_password : Copernicus password for ODP auth (falls back to CDSE_PASSWORD env var)

    Returns
    -------
    list of absolute paths to all downloaded GeoTIFF files
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
    existing_dem  = glob.glob(os.path.join(output_dir, "dem_*.tif"))
    existing_sar  = glob.glob(os.path.join(output_dir, "sar_*.tif"))

    # Fast path: all needed types already cached
    all_cached = existing_ndvi and existing_dem and (not include_sar or existing_sar)
    if all_cached:
        logger.info(
            "All satellite data cached for AOI %s (%d NDVI, %d DEM, %d SAR); skipping fetch.",
            aoi_id, len(existing_ndvi), len(existing_dem), len(existing_sar),
        )
        return existing_ndvi + existing_dem + existing_sar

    # Establish openEO connection (shared for NDVI + DEM)
    try:
        connection = connect()
        bbox = build_bbox(aoi_gdf)
    except (ConnectionError, ImportError) as exc:
        logger.error("openEO connection failed: %s", exc)
        raise

    temporal_extent = build_temporal_extent(days_back)
    all_paths = []

    # --- Sentinel-2 NDVI ---
    if existing_ndvi:
        logger.info("NDVI cached for AOI %s; skipping S2 fetch.", aoi_id)
        all_paths.extend(existing_ndvi)
    else:
        try:
            ndvi_paths = fetch_sentinel2(connection, bbox, temporal_extent, output_dir, aoi_id)
            if not ndvi_paths:
                logger.warning(
                    "Sentinel-2 returned no data for AOI %s (check cloud cover).", aoi_id
                )
            all_paths.extend(ndvi_paths)
        except Exception as exc:
            logger.error("Sentinel-2 fetch failed for AOI %s: %s", aoi_id, exc)

    # --- Copernicus DEM (non-fatal) ---
    if existing_dem:
        logger.info("DEM cached for AOI %s; skipping DEM fetch.", aoi_id)
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
            logger.warning("DEM fetch failed for AOI %s (%s); using synthetic elevation.", aoi_id, exc)

    # --- Sentinel-1 SAR via ODP (non-fatal, optional) ---
    if include_sar:
        if existing_sar:
            logger.info("SAR cached for AOI %s; skipping ODP fetch.", aoi_id)
            all_paths.extend(existing_sar)
        else:
            username = cdse_username or os.environ.get("CDSE_USER", "")
            password = cdse_password or os.environ.get("CDSE_PASSWORD", "")
            if not username or not password:
                logger.warning(
                    "SAR fetch requested but CDSE_USER/CDSE_PASSWORD not set; skipping."
                )
            else:
                try:
                    from core.ingest.loaders.odp_loader import fetch_sar
                    sar_paths = fetch_sar(
                        bbox, temporal_extent, output_dir, aoi_id, username, password
                    )
                    if sar_paths:
                        logger.info("SAR fetched: %d file(s).", len(sar_paths))
                        all_paths.extend(sar_paths)
                    else:
                        logger.warning("SAR returned no data for AOI %s.", aoi_id)
                except Exception as exc:
                    logger.warning("SAR fetch failed for AOI %s (%s); continuing without SAR.", aoi_id, exc)

    return all_paths
