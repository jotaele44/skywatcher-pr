"""DATABASE ACCESS + SCHEMA (mission responsibility 15)

Connection configuration, DB-path resolution, schema location, and schema
validation for the Skywatcher FR24 SQLite database. The DDL itself lives in
``schemas/database_schema.sql`` and is applied by :mod:`.database_migrations`.

DB-path precedence (mission Phase 3):
    1. explicit ``db`` argument (CLI ``--db PATH``)
    2. ``SKYWATCHER_DB`` environment variable
    3. ``./data/skywatcher.db`` (relative to CWD)

This module NEVER creates or populates an operational database on import. Callers
must explicitly request a connection. ``skywatcher.db`` is not a build artifact.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Optional, Union

__all__ = [
    "DatabaseError",
    "SchemaValidationError",
    "REPO_ROOT",
    "SCHEMA_SQL_PATH",
    "DEFAULT_DB_RELATIVE",
    "EXPECTED_TABLES",
    "resolve_db_path",
    "connect",
    "read_schema_sql",
    "get_schema_version",
    "list_tables",
    "foreign_keys_enabled",
    "validate_schema",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL_PATH = REPO_ROOT / "schemas" / "database_schema.sql"
DEFAULT_DB_RELATIVE = Path("data") / "skywatcher.db"

EXPECTED_TABLES = (
    "schema_version",
    "ingestion_batches",
    "screenshots",
    "ocr_observations",
    "aircraft",
    "flights",
    "flight_screenshots",
    "track_points",
    "anomalies",
    "processing_failures",
)


class DatabaseError(RuntimeError):
    """Base class for database configuration/initialization errors."""


class SchemaValidationError(DatabaseError):
    """Raised (or reported) when the DB schema does not match expectations."""


def resolve_db_path(
    db: Optional[Union[str, Path]] = None,
    *,
    env: Optional[dict] = None,
) -> Path:
    """Resolve the DB path using the documented precedence.

    Does not create the file or its parent; purely computes the path.
    """
    if db:
        return Path(db)
    environ = os.environ if env is None else env
    env_val = environ.get("SKYWATCHER_DB")
    if env_val:
        return Path(env_val)
    return DEFAULT_DB_RELATIVE


def connect(
    db_path: Union[str, Path],
    *,
    create_parent: bool = True,
    readonly: bool = False,
) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys ON.

    Write mode (default): creates the parent dir if needed, opens read-write, and
    enables WAL journaling. ``readonly=True`` opens an existing DB with a
    ``mode=ro`` URI — it never creates the file and never writes WAL/SHM
    sidecars, so validation/status/export inspection paths cannot mutate disk.
    Raises :class:`DatabaseError` on failure (including a missing file in
    read-only mode).
    """
    p = Path(db_path)
    if readonly:
        if not p.is_file():
            raise DatabaseError(f"database not found: {p}")
        try:
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        except sqlite3.Error as exc:  # noqa: BLE001
            raise DatabaseError(f"cannot open database read-only {p}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")  # harmless in read-only
        return conn
    if create_parent and p.parent and not p.parent.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001
            raise DatabaseError(f"cannot create DB directory {p.parent}: {exc}") from exc
    try:
        conn = sqlite3.connect(str(p))
    except sqlite3.Error as exc:  # noqa: BLE001
        raise DatabaseError(f"cannot open database {p}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def read_schema_sql() -> str:
    """Return the canonical schema DDL text."""
    if not SCHEMA_SQL_PATH.is_file():
        raise DatabaseError(f"schema file missing: {SCHEMA_SQL_PATH}")
    return SCHEMA_SQL_PATH.read_text(encoding="utf-8")


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none/no table."""
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    val = row["v"] if isinstance(row, sqlite3.Row) else row[0]
    return int(val) if val is not None else 0


def list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] if isinstance(r, sqlite3.Row) else r[0] for r in rows]


def foreign_keys_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    val = row[0] if row is not None else 0
    return bool(val)


def validate_schema(conn: sqlite3.Connection) -> List[str]:
    """Return a list of schema problems (empty == valid).

    Checks that every expected table exists and that foreign keys are enabled.
    Does not write anything.
    """
    problems: List[str] = []
    present = set(list_tables(conn))
    for table in EXPECTED_TABLES:
        if table not in present:
            problems.append(f"missing table: {table}")
    if not foreign_keys_enabled(conn):
        problems.append("foreign_keys pragma is OFF")
    return problems
