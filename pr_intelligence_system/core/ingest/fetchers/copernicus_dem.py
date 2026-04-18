"""
Copernicus GLO-30 DEM Fetcher
==============================
Fetches 30 m global DEM tiles from the AWS public S3 bucket
(s3://copernicus-dem-30m).  No credentials required.

Tiles are 1-degree × 1-degree Cloud-Optimised GeoTIFFs.  Multiple tiles
covering the AOI are merged with rasterio and sampled to a point DataFrame.

The merged DEM is also stored in a module-level cache so that
terrain_bathy_engine.py can replace its synthetic elevation proxy with
real elevation values during Step 2 of the pipeline.

Output: DataFrame with lat, lon, raster_value (elevation m), source_file,
        source_format='copernicus_dem', data_type='dem'.
"""

import os
import logging
import tempfile
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output, aoi_tile_list
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'copernicus_dem')
S3_BUCKET_DEM = 'copernicus-dem-30m'

# Module-level DEM cache populated by fetch_copernicus_dem()
_DEM_CACHE: pd.DataFrame = None


def get_cached_dem() -> pd.DataFrame:
    """Return the most recently fetched DEM DataFrame, or None if not yet fetched."""
    return _DEM_CACHE


def lookup_elevation(lat: float, lon: float, tolerance_deg: float = 0.05) -> float:
    """Return elevation (m) at the nearest cached DEM point within tolerance_deg.

    Returns NaN if the cache is empty or no point is within tolerance.
    """
    global _DEM_CACHE
    if _DEM_CACHE is None or len(_DEM_CACHE) == 0:
        return float('nan')

    dem_lats = _DEM_CACHE['lat'].values
    dem_lons = _DEM_CACHE['lon'].values
    dists2   = (dem_lats - lat) ** 2 + (dem_lons - lon) ** 2

    idx = int(np.argmin(dists2))
    if np.sqrt(dists2[idx]) > tolerance_deg:
        return float('nan')

    return float(_DEM_CACHE['raster_value'].values[idx])


def _s3_key_for_tile(lat_sw: int, lon_sw: int) -> str:
    """Build the S3 key for a GLO-30 DEM tile given its south-west corner."""
    ns = 'N' if lat_sw >= 0 else 'S'
    ew = 'E' if lon_sw >= 0 else 'W'
    lat_abs = abs(lat_sw)
    lon_abs = abs(lon_sw)
    folder = (
        f"Copernicus_DSM_COG_10_{ns}{lat_abs:02d}_00_{ew}{lon_abs:03d}_00_DEM"
    )
    filename = f"{folder}.tif"
    return f"{folder}/{filename}"


def _download_tile(s3_client, lat_sw: int, lon_sw: int, output_dir: str) -> str:
    """Download a single DEM tile to output_dir and return the local path.

    Returns None if the tile does not exist on S3 (ocean tiles are absent).
    """
    key = _s3_key_for_tile(lat_sw, lon_sw)
    filename = os.path.basename(key)
    local_path = os.path.join(output_dir, filename)

    if os.path.exists(local_path):
        logger.info(f"Copernicus DEM: cache hit {filename}")
        return local_path

    logger.info(f"Copernicus DEM S3: downloading {key}")
    try:
        s3_client.download_file(S3_BUCKET_DEM, key, local_path)
        return local_path
    except Exception as exc:
        logger.debug(f"Copernicus DEM: tile {key} not found (may be ocean): {exc}")
        return None


def fetch_copernicus_dem(
    aoi: tuple = DEFAULT_AOI,
    output_dir: str = DEFAULT_CACHE_DIR,
    store_global_cache: bool = True,
) -> pd.DataFrame:
    """Fetch Copernicus GLO-30 DEM tiles from AWS S3 (no credentials required).

    Downloads all 1-degree tiles covering the AOI, merges them with rasterio,
    samples to point features, and optionally stores in the module-level cache
    for use by terrain_bathy_engine.py.

    Returns DataFrame with: lat, lon, raster_value (elevation m), source_file,
    source_format='copernicus_dem', data_type='dem'.
    On any failure returns empty DataFrame.
    """
    global _DEM_CACHE

    try:
        import boto3
        import rasterio
        from rasterio.merge import merge as rasterio_merge
        from botocore import UNSIGNED
        from botocore.config import Config
        from core.ingest.loaders.raster_loader import load_raster

        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        os.makedirs(output_dir, exist_ok=True)

        tiles = aoi_tile_list(aoi)
        logger.info(f"Copernicus DEM: fetching {len(tiles)} tile(s) for AOI {aoi}")

        local_paths = []
        for (lat_sw, lon_sw) in tiles:
            path = _download_tile(s3, lat_sw, lon_sw, output_dir)
            if path is not None:
                local_paths.append(path)

        if not local_paths:
            logger.warning("Copernicus DEM: no tiles downloaded – returning empty DataFrame")
            return empty_fetcher_df(['data_type'])

        if len(local_paths) == 1:
            merged_path = local_paths[0]
        else:
            # Merge multiple tiles into a single in-memory mosaic saved to a temp file
            src_files = [rasterio.open(p) for p in local_paths]
            try:
                mosaic, transform = rasterio_merge(src_files)
                merged_path = os.path.join(output_dir, 'dem_merged.tif')
                profile = src_files[0].profile.copy()
                profile.update({
                    'height':    mosaic.shape[1],
                    'width':     mosaic.shape[2],
                    'transform': transform,
                })
                with rasterio.open(merged_path, 'w', **profile) as dst:
                    dst.write(mosaic)
                logger.info(f"Copernicus DEM: merged {len(local_paths)} tiles → {merged_path}")
            finally:
                for src in src_files:
                    src.close()

        df = load_raster(merged_path)
        if len(df) == 0:
            logger.warning("Copernicus DEM: load_raster returned empty DataFrame")
            return empty_fetcher_df(['data_type'])

        df['source_format'] = 'copernicus_dem'
        df['data_type']     = 'dem'
        df = validate_fetcher_output(df, 'CopernicusDEM')

        if store_global_cache:
            _DEM_CACHE = df.copy()
            logger.info(f"Copernicus DEM: cache populated with {len(_DEM_CACHE)} points")

        register_loaded_file(merged_path, 'copernicus_dem', len(df))
        logger.info(f"Copernicus DEM: {len(df)} elevation points returned")
        return df

    except ImportError as exc:
        logger.warning(f"Copernicus DEM: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['data_type'])
    except Exception as exc:
        logger.warning(f"Copernicus DEM fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['data_type'])
