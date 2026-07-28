"""Canonical source-control and deterministic-export policy."""
from __future__ import annotations

from pathlib import PurePosixPath

EXPORT_EXCLUDED_PREFIXES = (
    "frontend/", "data/", "var/", "tile_cache/", "exports/federation/",
    "reports/runtime/", "reports/maintenance/", "build/", "dist/", "htmlcov/",
)
FORBIDDEN_NAMES = {
    ".DS_Store", "__MACOSX", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".coverage",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".whl"}
FORBIDDEN_PREFIXES = (
    "Archive/", "var/", "tile_cache/", "frontend/node_modules/", "frontend/dist/",
    "build/", "dist/", "htmlcov/", "reports/runtime/", "reports/maintenance/",
)
FORBIDDEN_PATHS = {"coverage.xml"}


def is_export_excluded(path: str) -> bool:
    return path.startswith(EXPORT_EXCLUDED_PREFIXES)


def hygiene_violations(paths: list[str]) -> list[str]:
    bad: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        if raw in FORBIDDEN_PATHS or raw.startswith(FORBIDDEN_PREFIXES) or any(part in FORBIDDEN_NAMES or part.endswith(".egg-info") for part in path.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith("._"):
            bad.append(raw)
    return sorted(set(bad))
