"""CLI SUPPORT: path resolution + status (mission Phase 4 helpers)

Pure, unit-testable helpers backing the ``run_all.py`` entrypoint: screenshot
image-directory resolution (with the documented precedence and an actionable
error) and a read-only database status summary.

Image-dir precedence (mission Phase 4):
    1. --image-dir PATH
    2. SKYWATCHER_IMAGE_DIR
    3. ./inputs/screenshots      (replaces the hosted-only /mnt/user-data/uploads)

These helpers never process screenshot contents; ``resolve_image_dir`` only
resolves and existence-checks a path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from . import database as db

__all__ = [
    "DEFAULT_IMAGE_DIR_RELATIVE",
    "ImageDirUnavailableError",
    "resolve_image_dir",
    "database_status",
]

DEFAULT_IMAGE_DIR_RELATIVE = Path("inputs") / "screenshots"


class ImageDirUnavailableError(RuntimeError):
    """Raised when the resolved screenshot directory does not exist."""


def resolve_image_dir(
    image_dir: Optional[Union[str, Path]] = None,
    *,
    env: Optional[dict] = None,
    require_exists: bool = True,
) -> Path:
    """Resolve the screenshot input directory using the documented precedence.

    If ``require_exists`` and the resolved directory is missing, raise
    :class:`ImageDirUnavailableError` with an actionable message naming the
    resolved path and how to override it.
    """
    environ = os.environ if env is None else env
    if image_dir:
        resolved = Path(image_dir)
        source = "--image-dir"
    elif environ.get("SKYWATCHER_IMAGE_DIR"):
        resolved = Path(environ["SKYWATCHER_IMAGE_DIR"])
        source = "SKYWATCHER_IMAGE_DIR"
    else:
        resolved = DEFAULT_IMAGE_DIR_RELATIVE
        source = "default (./inputs/screenshots)"

    if require_exists and not resolved.is_dir():
        raise ImageDirUnavailableError(
            f"screenshot directory not found: {resolved} (from {source}). "
            f"Provide --image-dir PATH, set SKYWATCHER_IMAGE_DIR, or create "
            f"{DEFAULT_IMAGE_DIR_RELATIVE}."
        )
    return resolved


def database_status(db_path: Union[str, Path]) -> dict:
    """Return a read-only status summary of the DB (row counts per table).

    Does not write. If the DB/schema is absent, reports schema_version 0 and
    an empty counts map rather than raising.
    """
    # Read-only: never create the DB file. Report gracefully if absent.
    if not Path(db_path).is_file():
        return {"db_path": str(db_path), "exists": False, "schema_version": 0, "row_counts": {}}
    conn = db.connect(db_path, readonly=True)
    try:
        version = db.get_schema_version(conn)
        present = set(db.list_tables(conn))
        counts = {}
        for table in db.EXPECTED_TABLES:
            if table in present:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                counts[table] = int(row["n"] if hasattr(row, "keys") else row[0])
        return {
            "db_path": str(db_path),
            "exists": True,
            "schema_version": version,
            "row_counts": counts,
        }
    finally:
        conn.close()
