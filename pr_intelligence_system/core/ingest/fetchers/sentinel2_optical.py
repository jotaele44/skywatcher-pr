"""
Sentinel-2 Optical Fetcher
===========================
Fetches Sentinel-2 L2A multispectral bands from the AWS public open-data
S3 bucket (s3://sentinel-s2-l2a).  No credentials required.

Default bands: B04 (Red, 665 nm) and B08 (NIR, 842 nm).
NDVI is computed when both bands are available.

Output: DataFrame with lat, lon, raster_value (B04 reflectance), ndvi,
        source_file, source_format, band, acquisition_date.
"""

import os
import math
import logging
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'sentinel2')
DEFAULT_BANDS = ['B04', 'B08']
S3_BUCKET_S2 = 'sentinel-s2-l2a'
MAX_SCENES = 2


def _latlon_to_mgrs_prefix(lat: float, lon: float) -> str:
    """Derive approximate MGRS tile prefix (UTM zone + lat band) from lat/lon.

    Returns a string like '19Q' used to filter S3 object keys.
    This is an approximation — does not handle polar regions or edge cases.
    """
    utm_zone = int((lon + 180.0) / 6.0) + 1

    lat_bands = 'CDEFGHJKLMNPQRSTUVWX'
    idx = int((lat + 80.0) / 8.0)
    idx = max(0, min(idx, len(lat_bands) - 1))
    lat_band = lat_bands[idx]

    return f"{utm_zone:02d}{lat_band}"


def _list_s3_scenes(s3_client, aoi: tuple, date_range: tuple, max_scenes: int) -> list:
    """List Sentinel-2 scene prefixes on S3 matching the AOI and date range."""
    min_lon, min_lat, max_lon, max_lat = aoi
    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    mgrs_prefix = _latlon_to_mgrs_prefix(center_lat, center_lon)

    start, end = date_range
    start_year = start[:4]
    start_month = start[5:7].lstrip('0') or '1'

    prefix = f'tiles/{mgrs_prefix[:2]}/{mgrs_prefix[2]}/{mgrs_prefix[2:]}/{start_year}/{start_month}/'
    logger.info(f"Sentinel-2 S3: listing prefix s3://{S3_BUCKET_S2}/{prefix}")

    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_S2, Prefix=prefix, Delimiter='/', MaxKeys=50
        )
        prefixes = [
            p['Prefix']
            for p in response.get('CommonPrefixes', [])
        ]
        return prefixes[:max_scenes]
    except Exception as exc:
        logger.warning(f"Sentinel-2 S3 listing failed: {exc}")
        return []


def _download_band(s3_client, scene_prefix: str, band: str, output_dir: str) -> str:
    """Download a single band JP2 file from S3 and return the local path."""
    # Band files live at R10m/{band}.jp2 for 10m bands
    resolution_map = {
        'B02': 'R10m', 'B03': 'R10m', 'B04': 'R10m', 'B08': 'R10m',
        'B05': 'R20m', 'B06': 'R20m', 'B07': 'R20m',
        'B11': 'R20m', 'B12': 'R20m',
    }
    res_folder = resolution_map.get(band, 'R10m')
    key = f"{scene_prefix}{res_folder}/{band}.jp2"

    filename = key.replace('/', '_')
    local_path = os.path.join(output_dir, filename)

    if os.path.exists(local_path):
        logger.info(f"Sentinel-2: cache hit {filename}")
        return local_path

    logger.info(f"Sentinel-2 S3: downloading {key}")
    os.makedirs(output_dir, exist_ok=True)
    s3_client.download_file(S3_BUCKET_S2, key, local_path)
    return local_path


def fetch_sentinel2_optical(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    bands: list = None,
    max_scenes: int = MAX_SCENES,
    output_dir: str = DEFAULT_CACHE_DIR,
    resolution: str = '10m',
) -> pd.DataFrame:
    """Fetch Sentinel-2 optical bands from AWS S3 open data (no credentials).

    Returns DataFrame with: lat, lon, raster_value (B04), ndvi (if B08 available),
    source_file, source_format='sentinel2_optical', band, acquisition_date.
    On any failure returns empty DataFrame.
    """
    if bands is None:
        bands = DEFAULT_BANDS

    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        from core.ingest.loaders.raster_loader import load_raster

        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        scene_prefixes = _list_s3_scenes(s3, aoi, date_range, max_scenes)

        if not scene_prefixes:
            logger.warning("Sentinel-2: no scenes found – returning empty DataFrame")
            return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])

        all_dfs = []

        for scene_prefix in scene_prefixes:
            band_dfs = {}
            for band in bands:
                try:
                    local_path = _download_band(s3, scene_prefix, band, output_dir)
                    df_band = load_raster(local_path)
                    if len(df_band) > 0:
                        band_dfs[band] = df_band
                        register_loaded_file(local_path, 'sentinel2_optical', len(df_band))
                except Exception as exc:
                    logger.warning(f"Sentinel-2: failed to fetch {band} from {scene_prefix}: {exc}")

            if not band_dfs:
                continue

            # Use B04 as primary raster_value
            primary_band = 'B04' if 'B04' in band_dfs else list(band_dfs.keys())[0]
            df_primary = band_dfs[primary_band].copy()
            df_primary['band'] = primary_band
            df_primary['source_format'] = 'sentinel2_optical'

            scene_date = scene_prefix.split('/')[-2] if '/' in scene_prefix else 'unknown'
            df_primary['acquisition_date'] = scene_date

            # Compute NDVI if both B04 and B08 are available
            if 'B04' in band_dfs and 'B08' in band_dfs:
                df_b4 = band_dfs['B04']
                df_b8 = band_dfs['B08']
                min_len = min(len(df_b4), len(df_b8))
                red = df_b4['raster_value'].values[:min_len].astype(float)
                nir = df_b8['raster_value'].values[:min_len].astype(float)
                ndvi = (nir - red) / (nir + red + 1e-10)
                df_primary = df_primary.iloc[:min_len].copy()
                df_primary['ndvi'] = ndvi
            else:
                df_primary['ndvi'] = np.nan

            all_dfs.append(df_primary)

        if not all_dfs:
            return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])

        result = pd.concat(all_dfs, ignore_index=True)
        result = validate_fetcher_output(result, 'Sentinel2Optical')
        logger.info(f"Sentinel-2: {len(result)} point features returned")
        return result

    except ImportError as exc:
        logger.warning(f"Sentinel-2: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])
    except Exception as exc:
        logger.warning(f"Sentinel-2 fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])
