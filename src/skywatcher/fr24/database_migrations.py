"""DATABASE INITIALIZATION + MIGRATIONS (mission responsibility 16)

Deterministic, idempotent, transactional, migration-aware, schema-versioned
initialization for the Skywatcher FR24 database.

Guarantees:
    * deterministic  — migrations run in fixed version order.
    * idempotent     — re-running initialize_database() on an up-to-date DB is a
                       no-op; all DDL is CREATE ... IF NOT EXISTS.
    * transactional  — each migration + its schema_version row commit together;
                       on error the migration is rolled back.
    * migration-aware— only migrations newer than the DB's recorded version run.
    * schema-versioned — every applied migration is recorded in schema_version.
    * FK-enabled     — connections open with PRAGMA foreign_keys = ON.
    * safe           — never drops/overwrites existing tables or rows.
    * validation-only— validate_only=True checks schema without writing.

It NEVER produces an operational skywatcher.db as a task deliverable; tests use
temporary databases only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Union

from . import database as db

__all__ = [
    "MigrationError",
    "Migration",
    "MIGRATIONS",
    "LATEST_VERSION",
    "apply_migrations",
    "initialize_database",
    "InitResult",
]


class MigrationError(db.DatabaseError):
    """Raised when a migration cannot be applied."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _migration_0001_base_schema(conn: sqlite3.Connection) -> None:
    """Apply the canonical base schema from schemas/database_schema.sql."""
    conn.executescript(db.read_schema_sql())


# Ordered migration ledger. Append new migrations with the next integer version;
# never edit or reorder an already-released migration.
MIGRATIONS: List[Migration] = [
    Migration(1, "base FR24 canonical schema (10 tables)", _migration_0001_base_schema),
]

LATEST_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Bootstrap the schema_version table so we can read the current version
    before any migration has run. Matches the DDL in database_schema.sql."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT    NOT NULL,
            applied_at  TEXT    NOT NULL
        )
        """
    )
    conn.commit()


def apply_migrations(
    conn: sqlite3.Connection,
    *,
    target: Optional[int] = None,
) -> List[int]:
    """Apply all pending migrations up to ``target`` (default: latest).

    Returns the list of version numbers actually applied (empty if up to date).
    Each migration and its schema_version bookkeeping commit atomically.
    """
    _ensure_version_table(conn)
    current = db.get_schema_version(conn)
    ceiling = LATEST_VERSION if target is None else target
    applied: List[int] = []
    for migration in MIGRATIONS:
        if migration.version <= current or migration.version > ceiling:
            continue
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_version (version, description, applied_at) "
                "VALUES (?, ?, ?)",
                (migration.version, migration.description, _utc_now_iso()),
            )
            conn.commit()
        except sqlite3.Error as exc:  # noqa: BLE001
            conn.rollback()
            raise MigrationError(
                f"migration {migration.version} ({migration.description}) failed: {exc}"
            ) from exc
        applied.append(migration.version)
    return applied


@dataclass
class InitResult:
    db_path: str
    validate_only: bool
    schema_version: int
    applied: List[int]
    problems: List[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def initialize_database(
    db_path: Union[str, Path],
    *,
    validate_only: bool = False,
    create_parent: bool = True,
) -> InitResult:
    """Initialize (or validate) the database at ``db_path``.

    validate_only=True opens the DB read-check only: it applies no migrations and
    reports schema problems (including "no schema applied yet"). Otherwise it
    applies pending migrations idempotently and then validates.
    """
    conn = db.connect(db_path, create_parent=create_parent)
    try:
        if validate_only:
            problems = list(db.validate_schema(conn))
            version = db.get_schema_version(conn)
            if version == 0 and "missing table: schema_version" not in problems:
                problems.append("no migrations applied (schema_version is empty)")
            return InitResult(str(db_path), True, version, [], problems)

        applied = apply_migrations(conn)
        problems = list(db.validate_schema(conn))
        version = db.get_schema_version(conn)
        return InitResult(str(db_path), False, version, applied, problems)
    finally:
        conn.close()
