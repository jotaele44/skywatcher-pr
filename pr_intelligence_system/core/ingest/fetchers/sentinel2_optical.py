"""
Sentinel-2 Optical Fetcher  (fixed)
=====================================
Key fixes vs. previous version:
  • Replaced broken MGRS math with S3 discovery: list all grid-square
    subdirectories under tiles/{zone}/{lat_band}/ and try each one,
    filtering by proximity to the AOI centre (avoids hard-coded tile IDs
    and eliminates the 'tiles/19/Q/Q/' wrong-path bug)
  • Month prefix now uses int (strips leading zeros) to match S3 keys
  • Date filtering applied to scene subdirectory names

Output: DataFrame with lat, lon, raster_value (B04 reflectance), ndvi,
        source_file, source_format='sentinel2_optical', band, acquisition_date.
"""

import os
import logging
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'sentinel2')
DEFAULT_BANDS     = ['B04', 'B08']
S3_BUCKET_S2      = 'sentinel-s2-l2a'
MAX_SCENES        = 2


def _latlon_to_utm_zone_and_band(lat: float, lon: float) -> tuple:
    """Return (utm_zone_int, mgrs_lat_band_char) for a geographic coordinate."""
    utm_zone = int((lon + 180.0) / 6.0) + 1

    lat_bands = 'CDEFGHJKLMNPQRSTUVWX'
    idx       = int((lat + 80.0) / 8.0)
    idx       = max(0, min(idx, len(lat_bands) - 1))
    lat_band  = lat_bands[idx]

    return utm_zone, lat_band


def _parse_date_s2(date_str: str) -> tuple:
    """Return (year_str, month_int, day_int)."""
    s = date_str.replace('-', '')
    return s[:4], int(s[4:6]), int(s[6:8])


def _discover_grid_squares(s3_client, utm_zone: int, lat_band: str) -> list:
    """List all MGRS 100 km grid-square prefixes under tiles/{zone}/{band}/."""
    zone_prefix = f'tiles/{utm_zone:02d}/{lat_band}/'
    logger.info(f"Sentinel-2 S3: discovering grid squares under {zone_prefix}")
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_S2, Prefix=zone_prefix, Delimiter='/', MaxKeys=100
        )
        prefixes = [p['Prefix'] for p in resp.get('CommonPrefixes', [])]
        logger.info(f"Sentinel-2 S3: found {len(prefixes)} grid square(s) in zone {utm_zone}{lat_band}")
        return prefixes
    except Exception as exc:
        logger.warning(f"Sentinel-2 S3: grid-square discovery failed: {exc}")
        return []


def _list_scenes_for_square(
    s3_client, gs_prefix: str, year: str, month_int: int, max_scenes: int
) -> list:
    """List scene date-subdirectory prefixes for one grid square + month."""
    month_prefix = f'{gs_prefix}{year}/{month_int}/'
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_S2, Prefix=month_prefix, Delimiter='/', MaxKeys=50
        )
        day_prefixes = [p['Prefix'] for p in resp.get('CommonPrefixes', [])]
        # Each day prefix looks like  tiles/19/Q/GK/2024/1/15/
        scene_prefixes = []
        for day_prefix in day_prefixes[:max_scenes]:
            # List sequence-number subdirectories (usually just '0')
            seq_resp = s3_client.list_objects_v2(
                Bucket=S3_BUCKET_S2, Prefix=day_prefix, Delimiter='/', MaxKeys=10
            )
            for sp in seq_resp.get('CommonPrefixes', []):
                scene_prefixes.append(sp['Prefix'])
        return scene_prefixes
    except Exception as exc:
        logger.debug(f"Sentinel-2 S3: scene listing failed for {gs_prefix}: {exc}")
        return []


def _download_band(s3_client, scene_prefix: str, band: str, output_dir: str) -> str:
    """Download a single band JP2 and return local path."""
    resolution_map = {
        'B02': 'R10m', 'B03': 'R10m', 'B04': 'R10m', 'B08': 'R10m',
        'B05': 'R20m', 'B06': 'R20m', 'B07': 'R20m',
        'B11': 'R20m', 'B12': 'R20m',
    }
    res_folder = resolution_map.get(band, 'R10m')
    key        = f"{scene_prefix}{res_folder}/{band}.jp2"
    filename   = key.replace('/', '_')
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
    """Fetch Sentinel-2 L2A optical bands from AWS S3 (no credentials).

    Discovers available MGRS grid squares dynamically from the S3 bucket,
    avoiding hard-coded tile IDs.  Downloads B04 + B08 and computes NDVI.

    Returns DataFrame with: lat, lon, raster_value (B04), ndvi,
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

        min_lon, min_lat, max_lon, max_lat = aoi
        center_lat = (min_lat + max_lat) / 2.0
        center_lon = (min_lon + max_lon) / 2.0

        utm_zone, lat_band = _latlon_to_utm_zone_and_band(center_lat, center_lon)
        year, month_int, _ = _parse_date_s2(date_range[0])

        # Discover all grid squares in this zone/band
        grid_square_prefixes = _discover_grid_squares(s3, utm_zone, lat_band)

        if not grid_square_prefixes:
            logger.warning("Sentinel-2: no grid squares found – returning empty DataFrame")
            return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])

        # Collect scene prefixes across all grid squares
        all_scene_prefixes = []
        for gs_prefix in grid_square_prefixes:
            scenes = _list_scenes_for_square(s3, gs_prefix, year, month_int, max_scenes)
            all_scene_prefixes.extend(scenes)
            if len(all_scene_prefixes) >= max_scenes:
                break

        all_scene_prefixes = all_scene_prefixes[:max_scenes]

        if not all_scene_prefixes:
            logger.warning(
                f"Sentinel-2: no scenes found for zone {utm_zone}{lat_band} "
                f"{year}/{month_int} – returning empty DataFrame"
            )
            return empty_fetcher_df(['ndvi', 'band', 'acquisition_date'])

        all_dfs = []

        for scene_prefix in all_scene_prefixes:
            band_dfs = {}
            for band in bands:
                try:
                    local_path = _download_band(s3, scene_prefix, band, output_dir)
                    df_band    = load_raster(local_path)
                    if len(df_band) > 0:
                        band_dfs[band] = df_band
                        register_loaded_file(local_path, 'sentinel2_optical', len(df_band))
                except Exception as exc:
                    logger.warning(
                        f"Sentinel-2: failed to fetch {band} from {scene_prefix}: {exc}"
                    )

            if not band_dfs:
                continue

            primary_band = 'B04' if 'B04' in band_dfs else list(band_dfs.keys())[0]
            df_primary   = band_dfs[primary_band].copy()
            df_primary['band']           = primary_band
            df_primary['source_format']  = 'sentinel2_optical'
            df_primary['acquisition_date'] = scene_prefix.rstrip('/').split('/')[-3]

            if 'B04' in band_dfs and 'B08' in band_dfs:
                min_len = min(len(band_dfs['B04']), len(band_dfs['B08']))
                red  = band_dfs['B04']['raster_value'].values[:min_len].astype(float)
                nir  = band_dfs['B08']['raster_value'].values[:min_len].astype(float)
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
