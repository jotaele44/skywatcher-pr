"""
ADS-B feed — configuration.

Env-driven configuration for the automated aircraft-state-vector poll.
Mirrors ``imagery/config.py``'s convention: load ``.env`` if present, then
read ``os.getenv`` with safe defaults. No credentials are ever hard-coded
here; provider secrets come from the environment only.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass

# ── Base directories ─────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("ADSB_BASE_DIR", Path(__file__).resolve().parent.parent))

# ── Puerto Rico AOI envelope ─────────────────────────────────────────────────
# Same envelope as imagery/config.py (both repos are PR-focused). bbox order
# here is (west, south, east, north), matching imagery/geo.py's convention;
# OpenSkyProvider translates to the OpenSky (min_lat, max_lat, min_lon,
# max_lon) order at the call site.
PR_LON_MIN = float(os.getenv("ADSB_PR_LON_MIN", "-68.2"))
PR_LON_MAX = float(os.getenv("ADSB_PR_LON_MAX", "-65.1"))
PR_LAT_MIN = float(os.getenv("ADSB_PR_LAT_MIN", "17.8"))
PR_LAT_MAX = float(os.getenv("ADSB_PR_LAT_MAX", "18.7"))
DEFAULT_BBOX = [PR_LON_MIN, PR_LAT_MIN, PR_LON_MAX, PR_LAT_MAX]

# ── Fetch settings ───────────────────────────────────────────────────────────
FETCH_TIMEOUT_S = int(os.getenv("ADSB_FETCH_TIMEOUT", "30"))
POLL_INTERVAL_S = int(os.getenv("ADSB_POLL_INTERVAL", "300"))

# ── OpenSky Network (OAuth2 client credentials; blank = anonymous access) ────
OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")

# ── Sink ──────────────────────────────────────────────────────────────────────
# Written through src/skywatcher/fr24/database.py's connect()/migration
# machinery, same DB-path precedence as the rest of the FR24 pipeline.
SKYWATCHER_DB = os.getenv("SKYWATCHER_DB", "")
