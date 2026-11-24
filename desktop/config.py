"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared PRII federation template; only this file
differs between repos.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Window title of the desktop app.
APP_TITLE = "Skywatcher"
APP_ID = "Skywatcher"
BRAND_ACCENT = "#0573e4"
BRAND_ACCENT_STRONG = "#075ba7"
ICON_PATH = REPO_ROOT / "assets" / "branding" / "icon-256.png"
SETUP_VERSION = 1
DATA_ENV_VAR = "SKYWATCHER_DATA_HOME"

# Dotted import path of the FastAPI application object.
APP_IMPORT = "server.backend.main:app"

# Directory containing the Vite frontend (with package.json).
FRONTEND_DIR = REPO_ROOT / "frontend"

# Vite build output served by the desktop app.
DIST_DIR = FRONTEND_DIR / "dist"

# Requirement files installed into the private .venv by desktop/setup.py.
REQUIREMENT_FILES = [
    REPO_ROOT / "server" / "backend" / "requirements.txt",
    REPO_ROOT / "requirements-desktop.txt",
]

# Health endpoint used to detect that the backend is up.
HEALTH_PATH = "/health"

# The frontend reads its API base from these scoped vars (see
# frontend/src/lib/app-params.js); blank them at build time so a developer
# .env.local can't point the desktop build at an external backend.
EXTRA_BUILD_ENV = {
    "VITE_SKYWATCHER_API_BASE_URL": "",
    "VITE_FEDERATION_API_BASE_URL": "",
}


def _launchpad_status() -> list[dict[str, str]]:
    """Readiness rows for the Launch Pad. Runs before the backend exists, so it
    reads the same files the backend will, honouring the same path overrides.
    """

    def count(db: Path, query: str) -> int | None:
        if not db.is_file():
            return None
        try:
            # mode=ro: a readiness check must never create or migrate a store.
            with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
                return int(conn.execute(query).fetchone()[0])
        except sqlite3.Error:
            return None

    archive_db = Path(os.environ.get("SKYWATCHER_DB") or REPO_ROOT / "data" / "skywatcher.db")
    cameras_root = Path(
        os.environ.get("SKYWATCHER_SKY_CAMERAS_ROOT") or REPO_ROOT / "data" / "sky_cameras"
    )
    airports = REPO_ROOT / "data" / "reference" / "pr_airports.jsonl"
    snapshots = count(archive_db, "SELECT COUNT(*) FROM flight_corpus_snapshots")
    pending = count(
        cameras_root / "submissions.sqlite",
        "SELECT COUNT(*) FROM submissions WHERE status = 'pending'",
    )
    airport_rows = (
        sum(1 for line in airports.read_text(encoding="utf-8").splitlines() if line.strip())
        if airports.is_file()
        else 0
    )
    return [
        {
            "label": "Reference data",
            "value": f"{airport_rows} airports" if airport_rows else "Missing",
            "status": "pass" if airport_rows else "fail",
            "detail": (
                "Puerto Rico airport reference set is available."
                if airport_rows
                else "data/reference/pr_airports.jsonl was not found."
            ),
        },
        {
            "label": "Flight archive",
            "value": "Empty" if not snapshots else f"{snapshots:,} snapshots",
            "status": "pass" if snapshots else "info",
            "detail": (
                f"Archived corpus snapshots in {archive_db}."
                if snapshots
                else "No corpus snapshot has been archived yet (Operator: Flight Archive)."
            ),
        },
        {
            "label": "Sky camera submissions",
            "value": "None" if not pending else f"{pending:,} pending",
            "status": "warn" if pending else "info",
            "detail": (
                "Submissions are waiting for a reviewer decision (Operator: Sky Cameras)."
                if pending
                else "No submissions are waiting for review."
            ),
        },
    ]


# Pre-launch screen shown by the shared runtime (prii_desktop.launchpad).
LAUNCHPAD = {
    "tagline": "PRII airspace and aircraft intelligence",
    "summary": (
        "Skywatcher is the federation's airspace producer: it turns FR24 "
        "captures and flight tracks into airspace observations, builds aircraft "
        "profiles, and exports airspace packages to TheHub. This is its "
        "diagnostic console for reviewing that work."
    ),
    "highlights": [
        "Airspace observations",
        "Aircraft profiles",
        "Flight archive",
        "Space-Track",
        "Sky cameras",
    ],
    "status": _launchpad_status,
    # Every route in frontend/src/App.jsx that the sidebar links to.
    "start_pages": [
        {"route": "/", "label": "Command Dashboard",
         "description": "Overview of observations, readiness and recent activity."},
        {"route": "/console", "label": "Interactive Console",
         "description": "Query aircraft profiles, flights and the review queue."},
        {"route": "/observations", "label": "Airspace Observations"},
        {"route": "/aircraft", "label": "Aircraft Profiles"},
        {"route": "/fr24", "label": "FR24 Intake"},
        {"route": "/routes", "label": "Route-Line Mining"},
        {"route": "/infrastructure", "label": "Infrastructure Links"},
        {"route": "/airports", "label": "PR Airports"},
        {"route": "/review", "label": "Manual Review"},
        {"route": "/export", "label": "Federation Export"},
        {"route": "/readiness", "label": "Readiness / Blockers"},
        {"route": "/calibration", "label": "SATIM Calibration"},
        {"route": "/analysis", "label": "Analysis Lenses"},
        {"route": "/spatial-truth", "label": "Aircraft Spatial Truth"},
        {"route": "/flight-archive", "label": "Flight Archive",
         "description": "Archived flight-corpus snapshots."},
        {"route": "/space-track", "label": "Space-Track Control"},
        {"route": "/space-track/sky", "label": "Sky Target Finder"},
        {"route": "/sky-cameras", "label": "Sky Cameras",
         "description": "Camera catalogue and submitted footage."},
    ],
    "guest": {
        "label": "Guest",
        "description": (
            "Read-only. Browse and query everything; archiving snapshots, "
            "editing records and camera submissions or decisions are refused."
        ),
    },
    # No token_env: with PRII_WRITE_TOKEN unset the backend already accepts
    # writes from this computer, which is what a local Operator session needs.
    "operator": {
        "label": "Operator",
        "description": (
            "Full access from this computer: archive flight-corpus snapshots, "
            "edit records, and accept or decide sky-camera submissions."
        ),
    },
    # The backend's two POSTs that only read (server/backend/main.py).
    "guest_guard": {"allow": ["POST /api/entities/*/filter", "POST /api/query"]},
    "options": [
        {
            "id": "camera_submissions_per_hour",
            "label": "Sky-camera submissions per hour",
            "kind": "choice",
            "env": "SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR",
            "default": "20",
            "choices": [["5", "5"], ["20", "20 (default)"], ["60", "60"], ["200", "200"]],
            "operator_only": True,
            "help": "Rate limit applied to the public camera-footage intake.",
        },
        {
            "id": "camera_max_upload_mb",
            "label": "Largest camera upload",
            "kind": "choice",
            "env": "SKYWATCHER_SKY_CAMERAS_MAX_UPLOAD_MB",
            "default": "100",
            "choices": [["25", "25 MB"], ["100", "100 MB (default)"], ["500", "500 MB"]],
            "operator_only": True,
            "help": "Size limit for one submitted video.",
        },
        {
            "id": "anthropic_api_key",
            "label": "Anthropic API key",
            "kind": "secret",
            "env": "ANTHROPIC_API_KEY",
            "help": (
                "Optional. Lets the console answer natural-language questions "
                "through the Anthropic API; this sends the question and matching "
                "profile data off this computer. It also needs the optional "
                "anthropic package (requirements-llm.txt); without both, answers "
                "stay deterministic and local."
            ),
        },
    ],
}
