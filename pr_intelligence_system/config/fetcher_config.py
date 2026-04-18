import os

# ── Area of interest ──────────────────────────────────────────────────────────
# Default: Puerto Rico and surrounding EEZ  (min_lon, min_lat, max_lon, max_lat)
DEFAULT_AOI = (
    float(os.environ.get('FETCHER_AOI_MIN_LON', '-67.5')),
    float(os.environ.get('FETCHER_AOI_MIN_LAT', '17.8')),
    float(os.environ.get('FETCHER_AOI_MAX_LON', '-65.0')),
    float(os.environ.get('FETCHER_AOI_MAX_LAT', '18.6')),
)

# ── Default date window ───────────────────────────────────────────────────────
DEFAULT_DATE_RANGE = (
    os.environ.get('FETCHER_DATE_START', '2024-01-01'),
    os.environ.get('FETCHER_DATE_END',   '2024-01-31'),
)

# ── Cache root (all fetchers write here) ──────────────────────────────────────
FETCHER_CACHE_ROOT = os.environ.get('FETCHER_CACHE_DIR', 'data/raw/fetcher_cache')

# ── Credential env-var names (values are NEVER stored here) ──────────────────
ENV_CDSE_USER     = 'CDSE_USER'       # Copernicus Data Space Ecosystem username
ENV_CDSE_PASSWORD = 'CDSE_PASSWORD'   # Copernicus Data Space Ecosystem password
ENV_FIRMS_API_KEY = 'FIRMS_API_KEY'   # NASA FIRMS map-service API key
