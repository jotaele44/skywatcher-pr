import os
from datetime import datetime, timedelta

# ── Area of interest ──────────────────────────────────────────────────────────
# Default: Puerto Rico and surrounding EEZ  (min_lon, min_lat, max_lon, max_lat)
DEFAULT_AOI = (
    float(os.environ.get('FETCHER_AOI_MIN_LON', '-67.5')),
    float(os.environ.get('FETCHER_AOI_MIN_LAT', '17.8')),
    float(os.environ.get('FETCHER_AOI_MAX_LON', '-65.0')),
    float(os.environ.get('FETCHER_AOI_MAX_LAT', '18.6')),
)

# ── Default date window (rolling 30-day window ending yesterday) ──────────────
_today     = datetime.utcnow().date()
_end_date  = (_today - timedelta(days=1)).strftime('%Y-%m-%d')
_start_date = (_today - timedelta(days=30)).strftime('%Y-%m-%d')

DEFAULT_DATE_RANGE = (
    os.environ.get('FETCHER_DATE_START', _start_date),
    os.environ.get('FETCHER_DATE_END',   _end_date),
)

# ── Cache root (all fetchers write here) ──────────────────────────────────────
FETCHER_CACHE_ROOT = os.environ.get('FETCHER_CACHE_DIR', 'data/raw/fetcher_cache')

# ── Credential env-var names (values are NEVER stored here) ──────────────────
ENV_CDSE_USER     = 'CDSE_USER'       # Copernicus Data Space Ecosystem username
ENV_CDSE_PASSWORD = 'CDSE_PASSWORD'   # Copernicus Data Space Ecosystem password
ENV_FIRMS_API_KEY = 'FIRMS_API_KEY'   # NASA FIRMS map-service API key
