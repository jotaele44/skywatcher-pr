"""
VIIRS / NASA FIRMS Thermal Anomaly Fetcher
===========================================
Fetches active fire and thermal anomaly detections from the NASA FIRMS
map-service CSV API.

The API endpoint is public and does not require a key for small AOI /
short date windows (≤10 days, ≤500 km²).  For larger queries set the
FIRMS_API_KEY environment variable.

Reference: https://firms.modaps.eosdis.nasa.gov/api/

Output: DataFrame with lat, lon, raster_value (bright_ti4 brightness
        temperature K), confidence, frp (fire radiative power MW),
        source_file, source_format='viirs_firms', acquisition_date.
"""

import os
import io
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT, ENV_FIRMS_API_KEY
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'firms')
FIRMS_BASE_URL    = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv'
DEFAULT_SOURCE    = 'VIIRS_SNPP_NRT'
MAX_DAYS          = 10   # FIRMS public limit without API key


def _date_range_to_days(date_range: tuple) -> int:
    """Convert (start, end) date strings to number of days (capped at MAX_DAYS)."""
    try:
        fmt = '%Y-%m-%d' if '-' in date_range[0] else '%Y%m%d'
        start = datetime.strptime(date_range[0], fmt)
        end   = datetime.strptime(date_range[1], fmt)
        days  = max(1, (end - start).days + 1)
        return min(days, MAX_DAYS)
    except Exception:
        return 1


def _build_url(api_key: str, source: str, aoi: tuple, days: int) -> str:
    """Build the FIRMS CSV download URL."""
    min_lon, min_lat, max_lon, max_lat = aoi
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    return f"{FIRMS_BASE_URL}/{api_key}/{source}/{bbox}/{days}"


def fetch_viirs_firms(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    source: str = DEFAULT_SOURCE,
    api_key: str = None,
    output_dir: str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Fetch VIIRS thermal anomaly data from NASA FIRMS.

    Uses the map-service area CSV download endpoint.
    No API key is required for small AOI / short time windows (≤10 days).

    Returns DataFrame with: lat, lon, raster_value (bright_ti4 K),
    confidence, frp, source_file, source_format='viirs_firms', acquisition_date.
    On any failure returns empty DataFrame.
    """
    try:
        import requests

        resolved_key = (
            api_key
            or os.environ.get(ENV_FIRMS_API_KEY, 'public')
        )

        days = _date_range_to_days(date_range)
        url  = _build_url(resolved_key, source, aoi, days)
        logger.info(f"VIIRS/FIRMS: requesting {url}")

        response = requests.get(url, timeout=30)

        if response.status_code == 400 and resolved_key == 'public':
            logger.warning(
                "VIIRS/FIRMS: public key rejected (query too large). "
                "Set FIRMS_API_KEY env var for larger requests."
            )
            return empty_fetcher_df(['confidence', 'frp', 'acquisition_date'])

        response.raise_for_status()

        if not response.text.strip():
            logger.info("VIIRS/FIRMS: API returned empty response (no detections in AOI/window)")
            return empty_fetcher_df(['confidence', 'frp', 'acquisition_date'])

        df = pd.read_csv(io.StringIO(response.text))

        if df.empty:
            logger.info("VIIRS/FIRMS: no thermal detections in requested AOI/date range")
            return empty_fetcher_df(['confidence', 'frp', 'acquisition_date'])

        # Column mapping
        rename_map = {}
        if 'latitude'  in df.columns: rename_map['latitude']  = 'lat'
        if 'longitude' in df.columns: rename_map['longitude'] = 'lon'
        if 'bright_ti4' in df.columns: rename_map['bright_ti4'] = 'raster_value'
        df = df.rename(columns=rename_map)

        # Confidence filter — keep 'nominal' and 'high' only
        if 'confidence' in df.columns:
            conf_order = {'low': 0, 'nominal': 1, 'high': 2}
            df['confidence_num'] = df['confidence'].map(
                lambda c: conf_order.get(str(c).lower(), 1)
            )
            df = df[df['confidence_num'] >= 1].drop(columns='confidence_num')

        # Acquisition date
        if 'acq_date' in df.columns:
            df['acquisition_date'] = df['acq_date']
        else:
            df['acquisition_date'] = date_range[0]

        # FRP column
        if 'frp' not in df.columns:
            df['frp'] = np.nan

        df['source_file']   = f'firms_viirs_{date_range[0]}_{date_range[1]}.csv'
        df['source_format'] = 'viirs_firms'

        df = validate_fetcher_output(df, 'VIIRSFRMS')

        os.makedirs(output_dir, exist_ok=True)
        cache_path = os.path.join(output_dir, df['source_file'].iloc[0])
        df.to_csv(cache_path, index=False)
        register_loaded_file(cache_path, 'viirs_firms', len(df))

        logger.info(f"VIIRS/FIRMS: {len(df)} thermal detections returned")
        return df

    except ImportError as exc:
        logger.warning(f"VIIRS/FIRMS: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['confidence', 'frp', 'acquisition_date'])
    except Exception as exc:
        logger.warning(f"VIIRS/FIRMS fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['confidence', 'frp', 'acquisition_date'])
