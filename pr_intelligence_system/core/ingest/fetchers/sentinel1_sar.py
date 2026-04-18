"""
Sentinel-1 SAR Fetcher
======================
Fetches Sentinel-1 GRD SAR scenes from:
  1. Copernicus Data Space Ecosystem (sentinelsat) — requires CDSE credentials
  2. AWS S3 open-data mirror (s3://sentinel-s1-l1c) — unsigned, no credentials

Falls back gracefully if network, credentials, or dependencies are unavailable.
Output: DataFrame with lat, lon, raster_value (VV backscatter), acquisition_date.
"""

import os
import logging
import tempfile
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'sentinel1')
S3_BUCKET_S1 = 'sentinel-s1-l1c'
MAX_SCENES = 3


def _load_raster_safe(filepath: str) -> pd.DataFrame:
    """Delegate to the existing raster_loader; return empty DF on failure."""
    try:
        from core.ingest.loaders.raster_loader import load_raster
        return load_raster(filepath)
    except Exception as exc:
        logger.warning(f"raster_loader failed for {filepath}: {exc}")
        return empty_fetcher_df()


def _fetch_via_sentinelsat(
    aoi: tuple,
    date_range: tuple,
    max_scenes: int,
    output_dir: str,
    username: str,
    password: str,
) -> list:
    """Download scenes via Copernicus Open Access Hub. Returns list of file paths."""
    from sentinelsat import SentinelAPI
    from core.ingest.fetchers.base import bbox_to_wkt

    api = SentinelAPI(username, password, 'https://apihub.copernicus.eu/apihub')
    footprint = bbox_to_wkt(aoi)
    start, end = date_range
    start_dt = start.replace('-', '') if '-' in start else start
    end_dt   = end.replace('-', '')   if '-' in end   else end

    products = api.query(
        footprint,
        date=(start_dt, end_dt),
        platformname='Sentinel-1',
        producttype='GRD',
    )
    products_df = api.to_dataframe(products)
    if products_df.empty:
        logger.info("Sentinel-1 (sentinelsat): no scenes found for AOI/date range")
        return []

    products_df = products_df.sort_values('beginposition', ascending=False)
    selected = products_df.head(max_scenes)

    os.makedirs(output_dir, exist_ok=True)
    downloaded = api.download_all(
        list(selected.index),
        directory_path=output_dir,
    )
    paths = [str(p['path']) for p in downloaded.downloaded.values()]
    logger.info(f"Sentinel-1 (sentinelsat): downloaded {len(paths)} scene(s)")
    return paths


def _fetch_via_s3(
    aoi: tuple,
    date_range: tuple,
    max_scenes: int,
    output_dir: str,
) -> list:
    """List and download GeoTIFF products from AWS S3 open-data mirror."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    os.makedirs(output_dir, exist_ok=True)

    start, end = date_range
    start_year = start[:4]

    prefix = f'GRD/{start_year}/'
    logger.info(f"Sentinel-1 S3: listing s3://{S3_BUCKET_S1}/{prefix}")

    response = s3.list_objects_v2(Bucket=S3_BUCKET_S1, Prefix=prefix, MaxKeys=200)
    if 'Contents' not in response:
        logger.info("Sentinel-1 S3: no objects found")
        return []

    keys = [obj['Key'] for obj in response['Contents'] if obj['Key'].endswith('.tif')]
    keys = keys[:max_scenes]

    paths = []
    for key in keys:
        filename = os.path.basename(key)
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

    Tries sentinelsat with CDSE credentials first; if unavailable falls back to
    the AWS S3 unsigned open-data path.  On any failure returns empty DataFrame.

    Output columns: lat, lon, raster_value (VV backscatter), source_file,
                    source_format, band, acquisition_date.
    """
    try:
        username = username or os.environ.get('CDSE_USER')
        password = password or os.environ.get('CDSE_PASSWORD')

        scene_paths = []

        # Path 1: sentinelsat
        if username and password:
            try:
                import sentinelsat  # noqa: F401
                scene_paths = _fetch_via_sentinelsat(
                    aoi, date_range, max_scenes, output_dir, username, password
                )
            except ImportError:
                logger.warning("sentinelsat not installed; skipping CDSE path")
            except Exception as exc:
                logger.warning(f"Sentinel-1 sentinelsat fetch failed: {exc}")

        # Path 2: AWS S3 open data
        if not scene_paths:
            try:
                import boto3  # noqa: F401
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
                df['band'] = 'VV'
                df['acquisition_date'] = os.path.basename(path)[:8]
                df['source_format'] = 'sentinel1_sar'
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
