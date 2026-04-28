"""
CHIRPS v2.0 Daily Precipitation Fetcher
========================================
Source  : https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/
Format  : GeoTIFF (gzip-compressed, ~10 MB/day)
Coverage: 50°S–50°N, 0.05° resolution (~5.6 km), daily since 1981-01-01
          Puerto Rico (~18°N) is within coverage.
No credentials required — public HTTP download.

Output: lat, lon, raster_value (precipitation mm/day), source_file,
        source_format='chirps_precip', acquisition_date.
On any failure returns empty DataFrame.
"""

import os
import gzip
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

CHIRPS_BASE_URL   = 'https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05'
DEFAULT_CACHE_DIR  = os.path.join(FETCHER_CACHE_ROOT, 'chirps')
CHIRPS_NODATA      = -9999.0


def _parse_date(date_str: str) -> datetime:
    s = date_str.replace('-', '')
    return datetime.strptime(s, '%Y%m%d')


def _chirps_url(dt: datetime) -> tuple:
    """Return (url, gz_filename) for a given date."""
    year  = dt.strftime('%Y')
    month = dt.strftime('%m')
    day   = dt.strftime('%d')
    gz_filename = f'chirps-v2.0.{year}.{month}.{day}.tif.gz'
    url         = f'{CHIRPS_BASE_URL}/{year}/{gz_filename}'
    return url, gz_filename


def _download_and_gunzip(url: str, gz_path: str, tif_path: str, requests_mod) -> bool:
    """Download gz file and decompress to tif_path. Returns True on success."""
    if os.path.exists(tif_path):
        logger.info(f"CHIRPS: cache hit {os.path.basename(tif_path)}")
        return True

    if not os.path.exists(gz_path):
        logger.info(f"CHIRPS: downloading {url}")
        try:
            resp = requests_mod.get(url, stream=True, timeout=90)
            if resp.status_code == 404:
                logger.debug(f"CHIRPS: 404 for {url}")
                return False
            resp.raise_for_status()
            with open(gz_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65_536):
                    f.write(chunk)
        except Exception as exc:
            logger.debug(f"CHIRPS: download failed for {url}: {exc}")
            if os.path.exists(gz_path):
                try:
                    os.remove(gz_path)
                except OSError:
                    pass
            return False

    logger.info(f"CHIRPS: decompressing {os.path.basename(gz_path)}")
    try:
        with gzip.open(gz_path, 'rb') as gz_in, open(tif_path, 'wb') as tif_out:
            tif_out.write(gz_in.read())
        return True
    except Exception as exc:
        logger.debug(f"CHIRPS: gunzip failed: {exc}")
        if os.path.exists(tif_path):
            try:
                os.remove(tif_path)
            except OSError:
                pass
        return False


def fetch_chirps_precip(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    output_dir: str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Fetch CHIRPS v2.0 daily precipitation via HTTP (no credentials).

    Tries `date_range[0]` first; falls back to that date − 1 day on
    HTTP 404 (CHIRPS is typically published with a 2-3 day latency).

    Returns DataFrame with: lat, lon, raster_value (mm/day),
    source_file, source_format='chirps_precip', acquisition_date.
    On any failure returns empty DataFrame.
    """
    try:
        import requests
        from core.ingest.loaders.raster_loader import load_raster

        os.makedirs(output_dir, exist_ok=True)

        primary_dt  = _parse_date(date_range[0])
        fallback_dt = primary_dt - timedelta(days=1)

        tif_path      = None
        resolved_date = None

        for dt in (primary_dt, fallback_dt):
            url, gz_filename = _chirps_url(dt)
            gz_path = os.path.join(output_dir, gz_filename)
            tp      = gz_path[:-3]   # strip .gz → .tif

            if _download_and_gunzip(url, gz_path, tp, requests):
                tif_path      = tp
                resolved_date = dt.strftime('%Y-%m-%d')
                break

        if tif_path is None:
            logger.warning("CHIRPS: could not download any file – returning empty DataFrame")
            return empty_fetcher_df(['acquisition_date'])

        df = load_raster(tif_path)
        if len(df) == 0:
            return empty_fetcher_df(['acquisition_date'])

        # Remove nodata values not caught by rasterio masking
        df = df[df['raster_value'] != CHIRPS_NODATA].copy()
        df = df[df['raster_value'] >= 0.0].copy()   # precipitation is non-negative

        min_lon, min_lat, max_lon, max_lat = aoi
        aoi_mask = (
            (df['lat'] >= min_lat) & (df['lat'] <= max_lat)
            & (df['lon'] >= min_lon) & (df['lon'] <= max_lon)
        )
        df = df[aoi_mask].copy()

        if len(df) == 0:
            logger.info("CHIRPS: no data in AOI – returning empty DataFrame")
            return empty_fetcher_df(['acquisition_date'])

        df['source_file']     = os.path.basename(tif_path)
        df['source_format']   = 'chirps_precip'
        df['acquisition_date'] = resolved_date

        register_loaded_file(tif_path, 'chirps_precip', len(df))
        df = validate_fetcher_output(df, 'CHIRPSPrecip')
        logger.info(
            f"CHIRPS: {len(df)} points in AOI; precip range "
            f"{df['raster_value'].min():.1f}–{df['raster_value'].max():.1f} mm/day"
        )
        return df

    except ImportError as exc:
        logger.warning(f"CHIRPS: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['acquisition_date'])
    except Exception as exc:
        logger.warning(f"CHIRPS fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['acquisition_date'])
