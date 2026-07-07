"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared PRII federation template; only this file
differs between repos.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Window title of the desktop app.
APP_TITLE = "Skywatcher — PRII Airspace Intelligence"

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
