"""
Sentinel-1 SAR Fetcher  (fixed)
================================
Key fixes vs. previous version:
  • S3 prefix now includes month + day extracted from date_range
    (was year-only, never reached measurement files)
  • Filter changed from '.tif' to '.tiff' (Sentinel-1 uses double-f)
  • Listing now targets IW/DV sub-path and filters for measurement/ VV files
"""

import os
import logging
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'sentinel1')
S3_BUCKET_S1 = 'sentinel-s1-l1c'
MAX_SCENES = 3


def _parse_date(date_str: str) -> tuple:
    """Return (year, month_int, day_int) from 'YYYYMMDD' or 'YYYY-MM-DD'."""
    s = date_str.replace('-', '')
    return s[:4], int(s[4:6]), int(s[6:8])


def _load_raster_safe(filepath: str) -> pd.DataFrame:
    try:
        from core.ingest.loaders.raster_loader import load_raster
        return load_raster(filepath)
    except Exception as exc:
        logger.warning(f"raster_loader failed for {filepath}: {exc}")
        return empty_fetcher_df()


def _fetch_via_sentinelsat(aoi, date_range, max_scenes, output_dir, username, password):
    from sentinelsat import SentinelAPI
    from core.ingest.fetchers.base import bbox_to_wkt

    api = SentinelAPI(username, password, 'https://apihub.copernicus.eu/apihub')
    footprint = bbox_to_wkt(aoi)
    start = date_range[0].replace('-', '')
    end   = date_range[1].replace('-', '')

    products = api.query(
        footprint,
        date=(start, end),
        platformname='Sentinel-1',
        producttype='GRD',
    )
    products_df = api.to_dataframe(products)
    if products_df.empty:
        logger.info("Sentinel-1 (sentinelsat): no scenes found")
        return []

    selected = products_df.sort_values('beginposition', ascending=False).head(max_scenes)
    os.makedirs(output_dir, exist_ok=True)
    downloaded = api.download_all(list(selected.index), directory_path=output_dir)
    paths = [str(p['path']) for p in downloaded.downloaded.values()]
    logger.info(f"Sentinel-1 (sentinelsat): downloaded {len(paths)} scene(s)")
    return paths


def _fetch_via_s3(aoi, date_range, max_scenes, output_dir):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    os.makedirs(output_dir, exist_ok=True)

    year, month_int, day_int = _parse_date(date_range[0])

    # Correct prefix: include year/month/day and IW mode directory
    prefix = f'GRD/{year}/{month_int}/{day_int}/IW/'
    logger.info(f"Sentinel-1 S3: listing s3://{S3_BUCKET_S1}/{prefix}")

    response = s3.list_objects_v2(Bucket=S3_BUCKET_S1, Prefix=prefix, MaxKeys=1000)
    if 'Contents' not in response:
        logger.info(f"Sentinel-1 S3: no objects found under {prefix}")
        return []

    # Filter for measurement VV polarisation TIFF files (double-f extension)
    keys = [
        obj['Key'] for obj in response['Contents']
        if obj['Key'].endswith('.tiff')
        and '/measurement/' in obj['Key']
        and 'vv' in obj['Key'].lower()
    ]

    if not keys:
        logger.info("Sentinel-1 S3: no VV measurement .tiff files found for this date")
        return []

    paths = []
    for key in keys[:max_scenes]:
        filename   = key.replace('/', '_')
        local_path = os.path.join(output_dir, filename)
        if os.path.exists(local_path):
            logger.info(f"Sentinel-1 S3: cache hit {filename}")
        else:
            logger.info(f"Sentinel-1 S3: downloading {key}")
            try:
                s3.download_file(S3_BUCKET_S1, key, local_path)
            except Exception as exc:
                logger.warning(f"Sentinel-1 S3: download failed for {key}: {exc}")
                continue
        paths.append(local_path)

    return paths


def fetch_sentinel1_sar(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    max_scenes: int = MAX_SCENES,
    output_dir: str = DEFAULT_CACHE_DIR,
    username: str = None,
    password: str = None,
) -> pd.DataFrame:
    """Fetch Sentinel-1 SAR scenes and return a point-features DataFrame.

    Tries sentinelsat (CDSE credentials) first; falls back to AWS S3 unsigned.
    On any failure returns empty DataFrame.

    Output columns: lat, lon, raster_value (VV backscatter), source_file,
                    source_format, band, acquisition_date.
    """
    try:
        username = username or os.environ.get('CDSE_USER')
        password = password or os.environ.get('CDSE_PASSWORD')
        scene_paths = []

        if username and password:
            try:
                import sentinelsat  # noqa
                scene_paths = _fetch_via_sentinelsat(
                    aoi, date_range, max_scenes, output_dir, username, password
                )
            except ImportError:
                logger.warning("sentinelsat not installed; skipping CDSE path")
            except Exception as exc:
                logger.warning(f"Sentinel-1 sentinelsat fetch failed: {exc}")

        if not scene_paths:
            try:
                import boto3  # noqa
                scene_paths = _fetch_via_s3(aoi, date_range, max_scenes, output_dir)
            except ImportError:
                logger.warning("boto3 not installed; cannot use S3 path for Sentinel-1")
            except Exception as exc:
                logger.warning(f"Sentinel-1 S3 fetch failed: {exc}")

        if not scene_paths:
            logger.warning("Sentinel-1: no scenes retrieved – returning empty DataFrame")
            return empty_fetcher_df(['band', 'acquisition_date'])

        all_dfs = []
        for path in scene_paths:
            df = _load_raster_safe(path)
            if len(df) > 0:
                df['band']           = 'VV'
                df['acquisition_date'] = os.path.basename(path)[:8]
                df['source_format']  = 'sentinel1_sar'
                all_dfs.append(df)
                register_loaded_file(path, 'sentinel1_sar', len(df))

        if not all_dfs:
            return empty_fetcher_df(['band', 'acquisition_date'])

        result = pd.concat(all_dfs, ignore_index=True)
        result = validate_fetcher_output(result, 'Sentinel1SAR')
        logger.info(f"Sentinel-1: {len(result)} point features returned")
        return result

    except Exception as exc:
        logger.warning(f"Sentinel-1 fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['band', 'acquisition_date'])
