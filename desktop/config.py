"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared PRII federation template; only this file
differs between repos.
"""

from __future__ import annotations

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
]

# Desktop-only deps, installed by desktop/setup.py alongside REQUIREMENT_FILES.
# pyproject.toml's [project.optional-dependencies].desktop extra is this
# repo's source of truth for these; inlined here (rather than a separate
# requirements-desktop.txt) since desktop/setup.py installs plain pip specs,
# not project extras.
EXTRA_PIP_SPECS = [
    "pywebview>=6.2.1",
    "prii-desktop @ git+https://github.com/jotaele44/thehub-pr.git@f2b81769924689b4d959554928810b1d7b7ef3d6#subdirectory=packages/prii_desktop",
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
