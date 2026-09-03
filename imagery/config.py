"""
Imagery — configuration.

Env-driven configuration for the imagery providers and cache. Mirrors the
``earthgpt/config.py`` convention: load ``.env`` if present, then read
``os.getenv`` with iOS-safe defaults. No credentials are ever hard-coded here;
provider secrets come from the environment only.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass

# ── Base directories ─────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("IMAGERY_BASE_DIR", Path(__file__).resolve().parent.parent))
# Cache fetched imagery under the git-ignored tile_cache/ tree.
CACHE_DIR = Path(os.getenv("IMAGERY_CACHE_DIR", BASE_DIR / "tile_cache" / "imagery"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Puerto Rico AOI envelope ─────────────────────────────────────────────────
# Matches readiness/satellite_ingest.py and the satellite_source_manifest schema
# (both repos are PR-focused). bbox order is (west, south, east, north).
PR_LON_MIN = float(os.getenv("IMAGERY_PR_LON_MIN", "-68.2"))
PR_LON_MAX = float(os.getenv("IMAGERY_PR_LON_MAX", "-65.1"))
PR_LAT_MIN = float(os.getenv("IMAGERY_PR_LAT_MIN", "17.8"))
PR_LAT_MAX = float(os.getenv("IMAGERY_PR_LAT_MAX", "18.7"))

# ── Fetch settings ───────────────────────────────────────────────────────────
FETCH_TIMEOUT_S = int(os.getenv("IMAGERY_FETCH_TIMEOUT", "30"))
FETCH_RETRIES = int(os.getenv("IMAGERY_FETCH_RETRIES", "3"))
USER_AGENT = os.getenv("IMAGERY_USER_AGENT", "spatial-rag-imagery/0.1")

# Default half-width (degrees) of the bbox built around a single lat/lon point.
DEFAULT_BUFFER_DEG = float(os.getenv("IMAGERY_BUFFER_DEG", "0.05"))
# Default output raster size (px) for WMS/Process GetMap requests.
DEFAULT_IMAGE_SIZE = int(os.getenv("IMAGERY_IMAGE_SIZE", "512"))
DEFAULT_PROVIDER = os.getenv("IMAGERY_DEFAULT_PROVIDER", "gibs")

# ── NASA GIBS (no auth) ──────────────────────────────────────────────────────
GIBS_WMS_URL = os.getenv(
    "IMAGERY_GIBS_WMS_URL",
    "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi",
)
GIBS_DEFAULT_LAYER = os.getenv(
    "IMAGERY_GIBS_LAYER", "MODIS_Terra_CorrectedReflectance_TrueColor"
)

# ── Sentinel Hub (OAuth2 client credentials) ─────────────────────────────────
SENTINELHUB_CLIENT_ID = os.getenv("SENTINELHUB_CLIENT_ID", "")
SENTINELHUB_CLIENT_SECRET = os.getenv("SENTINELHUB_CLIENT_SECRET", "")
SENTINELHUB_BASE_URL = os.getenv(
    "IMAGERY_SENTINELHUB_BASE_URL", "https://services.sentinel-hub.com"
)
SENTINELHUB_TOKEN_URL = os.getenv(
    "IMAGERY_SENTINELHUB_TOKEN_URL",
    "https://services.sentinel-hub.com/oauth/token",
)
SENTINELHUB_COLLECTION = os.getenv("IMAGERY_SENTINELHUB_COLLECTION", "sentinel-2-l2a")

# ── Copernicus Data Space Ecosystem (CDSE) ───────────────────────────────────
# CDSE hosts a Sentinel-Hub-compatible Process/Catalog API plus a STAC catalogue.
COPERNICUS_CLIENT_ID = os.getenv("COPERNICUS_CLIENT_ID", "")
COPERNICUS_CLIENT_SECRET = os.getenv("COPERNICUS_CLIENT_SECRET", "")
COPERNICUS_BASE_URL = os.getenv(
    "IMAGERY_COPERNICUS_BASE_URL", "https://sh.dataspace.copernicus.eu"
)
COPERNICUS_TOKEN_URL = os.getenv(
    "IMAGERY_COPERNICUS_TOKEN_URL",
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
)
COPERNICUS_COLLECTION = os.getenv("IMAGERY_COPERNICUS_COLLECTION", "sentinel-2-l2a")

# ── Change detection ─────────────────────────────────────────────────────────
# Per-pixel normalized-difference threshold above which a pixel counts as changed.
CHANGE_PIXEL_THRESHOLD = float(os.getenv("IMAGERY_CHANGE_THRESHOLD", "0.15"))
