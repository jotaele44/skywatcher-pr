"""
NOAA OISST v2.1 Sea Surface Temperature Fetcher
================================================
Source : s3://noaa-oisst-v2.1 (public, unsigned boto3)
Key    : AVHRR/{YYYYMM}/{YYYYMMDD}.nc
Format : NetCDF4 — variable 'sst' shape (1, 720, 1440) in °C

Output: lat, lon, raster_value (SST °C), source_file,
        source_format='noaa_oisst', acquisition_date.
On any failure returns empty DataFrame.
"""

import os
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

S3_BUCKET_OISST   = 'noaa-oisst-v2.1'
DEFAULT_CACHE_DIR  = os.path.join(FETCHER_CACHE_ROOT, 'oisst')
MAX_RASTER_POINTS  = 5_000


def _parse_date(date_str: str) -> datetime:
    s = date_str.replace('-', '')
    return datetime.strptime(s, '%Y%m%d')


def _oisst_s3_key(dt: datetime) -> str:
    """Return the S3 key for a given date: AVHRR/{YYYYMM}/{YYYYMMDD}.nc"""
    ym  = dt.strftime('%Y%m')
    ymd = dt.strftime('%Y%m%d')
    return f'AVHRR/{ym}/{ymd}.nc'


def fetch_noaa_oisst(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    output_dir: str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Fetch NOAA OISST v2.1 daily sea-surface temperature from AWS S3.

    Tries the start date first; falls back to the previous day if the file
    is not yet published (NOAA publishes with a ~1-day lag).

    Returns DataFrame with: lat, lon, raster_value (SST °C),
    source_file, source_format='noaa_oisst', acquisition_date.
    On any failure returns empty DataFrame.
    """
    try:
        import boto3
        import netCDF4 as nc4
        from botocore import UNSIGNED
        from botocore.config import Config

        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        os.makedirs(output_dir, exist_ok=True)

        primary_dt  = _parse_date(date_range[0])
        fallback_dt = primary_dt - timedelta(days=1)

        local_path    = None
        resolved_date = None

        for dt in (primary_dt, fallback_dt):
            key      = _oisst_s3_key(dt)
            filename = os.path.basename(key)
            lp       = os.path.join(output_dir, filename)

            if os.path.exists(lp):
                logger.info(f"OISST: cache hit {filename}")
                local_path    = lp
                resolved_date = dt.strftime('%Y-%m-%d')
                break

            logger.info(f"OISST S3: downloading {key}")
            try:
                s3.download_file(S3_BUCKET_OISST, key, lp)
                local_path    = lp
                resolved_date = dt.strftime('%Y-%m-%d')
                break
            except Exception as exc:
                logger.debug(f"OISST: download failed for {key}: {exc}")

        if local_path is None:
            logger.warning("OISST: could not download any file – returning empty DataFrame")
            return empty_fetcher_df(['acquisition_date'])

        ds = nc4.Dataset(local_path, 'r')
        try:
            lat_arr = ds.variables['lat'][:].data.astype(float)  # (720,)
            lon_arr = ds.variables['lon'][:].data.astype(float)  # (1440,) 0–360

            sst_var = ds.variables['sst']
            sst_raw = sst_var[:]  # masked array shape (1, 720, 1440) or (720, 1440)
            if sst_raw.ndim == 3:
                sst_raw = sst_raw[0]   # drop time dim
            sst_arr = sst_raw.filled(np.nan).astype(float)
        finally:
            ds.close()

        # Normalise longitude from 0–360 to -180–180
        lon_arr[lon_arr > 180.0] -= 360.0

        lat_grid, lon_grid = np.meshgrid(lat_arr, lon_arr, indexing='ij')

        lat_flat = lat_grid.ravel()
        lon_flat = lon_grid.ravel()
        sst_flat = sst_arr.ravel()

        finite_mask = np.isfinite(sst_flat)
        lat_flat = lat_flat[finite_mask]
        lon_flat = lon_flat[finite_mask]
        sst_flat = sst_flat[finite_mask]

        min_lon, min_lat, max_lon, max_lat = aoi
        aoi_mask = (
            (lat_flat >= min_lat) & (lat_flat <= max_lat)
            & (lon_flat >= min_lon) & (lon_flat <= max_lon)
        )
        lat_flat = lat_flat[aoi_mask]
        lon_flat = lon_flat[aoi_mask]
        sst_flat = sst_flat[aoi_mask]

        if len(lat_flat) == 0:
            logger.info("OISST: no data in AOI – returning empty DataFrame")
            return empty_fetcher_df(['acquisition_date'])

        if len(lat_flat) > MAX_RASTER_POINTS:
            rng     = np.random.RandomState(42)
            indices = rng.choice(len(lat_flat), MAX_RASTER_POINTS, replace=False)
            lat_flat = lat_flat[indices]
            lon_flat = lon_flat[indices]
            sst_flat = sst_flat[indices]

        df = pd.DataFrame({
            'lat':              lat_flat,
            'lon':              lon_flat,
            'raster_value':     sst_flat,
            'source_file':      os.path.basename(local_path),
            'source_format':    'noaa_oisst',
            'acquisition_date': resolved_date,
        })

        register_loaded_file(local_path, 'noaa_oisst', len(df))
        df = validate_fetcher_output(df, 'NOAAOISST')
        logger.info(f"OISST: {len(df)} points in AOI; SST range "
                    f"{sst_flat.min():.1f}–{sst_flat.max():.1f} °C")
        return df

    except ImportError as exc:
        logger.warning(f"OISST: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['acquisition_date'])
    except Exception as exc:
        logger.warning(f"OISST fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['acquisition_date'])
