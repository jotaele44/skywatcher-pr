"""
ADS-B feeds — configuration.

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
# Mirrors imagery/config.py's FETCH_RETRIES: total attempts, not extra retries.
FETCH_RETRIES = int(os.getenv("ADSB_FETCH_RETRIES", "3"))

# ── Retention ─────────────────────────────────────────────────────────────────
# adsb_state_vectors is append-only by design (see schemas/adsb_state_vectors.sql)
# — no row is ever updated in place. This bounds long-term growth instead: each
# persist_batch() call prunes rows older than RETENTION_DAYS. 0 disables pruning.
RETENTION_DAYS = int(os.getenv("ADSB_RETENTION_DAYS", "30"))

# ── OpenSky Network (OAuth2 client credentials; blank = anonymous access) ────
OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")

# ── adsb.lol (keyless public aggregator, ODbL-1.0 data) ──────────────────────
# api.adsb.lol is the documented public REST API (https://api.adsb.lol/docs).
# The site base serves the static trace and replay (globe_history) files that
# the adsb.lol web map itself reads. The web map's internal ``re-api`` endpoint
# sits behind a bot-verification challenge and is deliberately NOT used.
ADSBLOL_API_BASE = os.getenv("ADSBLOL_API_BASE", "https://api.adsb.lol").rstrip("/")
ADSBLOL_SITE_BASE = os.getenv("ADSBLOL_SITE_BASE", "https://adsb.lol").rstrip("/")
ADSBLOL_USER_AGENT = os.getenv(
    "ADSBLOL_USER_AGENT", "skywatcher-pr/0.1 (+https://github.com/jotaele44/skywatcher-pr)"
)
# api.adsb.lol caps /v2/point radius at 250 NM.
ADSBLOL_MAX_RADIUS_NM = float(os.getenv("ADSBLOL_MAX_RADIUS_NM", "250"))
# Identical upstream requests inside this window are served from memory so
# several open browser tabs do not multiply load on the community service.
ADSBLOL_CACHE_TTL_S = float(os.getenv("ADSBLOL_CACHE_TTL_S", "2"))
# Completed replay (heatmap) chunks are immutable; cache them on disk.
ADSBLOL_CACHE_DIR = Path(os.getenv("ADSBLOL_CACHE_DIR", BASE_DIR / "data" / "cache" / "adsblol"))

# ── Sink ──────────────────────────────────────────────────────────────────────
# Written through src/skywatcher/fr24/database.py's connect()/migration
# machinery, same DB-path precedence as the rest of the FR24 pipeline.
SKYWATCHER_DB = os.getenv("SKYWATCHER_DB", "")
