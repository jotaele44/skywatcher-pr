"""
migrations.py — Idempotent SQLite migrations for priis.db.

Each migration helper takes a live sqlite3.Connection and is safe to call any
number of times. They introspect the schema via PRAGMA table_info, since
SQLite's ADD COLUMN does not support an IF NOT EXISTS clause across all
versions shipped with macOS.

Call these from anywhere that opens a priis.db connection: seed_demo.py,
ingest_tiger_pr.py, and the FastAPI lifespan hook in server/backend/main.py.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

log = logging.getLogger(__name__)


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> bool:
    """Return True if the column was added on this call."""
    existing = _existing_columns(conn, table)
    if column in existing:
        return False
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        log.info("migration: added %s.%s %s", table, column, column_type)
        return True
    except sqlite3.OperationalError as exc:
        # Race condition with a concurrent migrator, or the column was added
        # between our PRAGMA check and the ALTER. Re-check; suppress only if
        # the column now exists.
        if column in _existing_columns(conn, table):
            return False
        raise RuntimeError(
            f"failed to add {table}.{column}: {exc}"
        ) from exc


def ensure_sites_geoid_columns(conn: sqlite3.Connection) -> dict[str, bool]:
    """
    Add municipio_geoid + tract_geoid TEXT columns to the sites table if absent.

    Returns a dict mapping column name → True if it was added on this call,
    False if it was already present. Callers may log this for observability.
    """
    if "sites" not in _existing_tables(conn):
        # Fresh DB — schema_sqlite.sql will be applied separately. Nothing to
        # migrate yet; the schema file itself already defines the columns.
        return {"municipio_geoid": False, "tract_geoid": False}
    added = {
        "municipio_geoid": _add_column_if_missing(
            conn, "sites", "municipio_geoid", "TEXT"
        ),
        "tract_geoid": _add_column_if_missing(
            conn, "sites", "tract_geoid", "TEXT"
        ),
    }
    conn.commit()
    return added


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row[0] for row in cur.fetchall()}


# FR24 aircraft detail columns added to the events table. Without these, the
# registration (and other fields) extracted by scripts/fr24_vision_ingest.py
# were silently dropped at ingest. column name → SQLite type.
_EVENTS_AIRCRAFT_COLUMNS = {
    "registration":     "TEXT",
    "callsign":         "TEXT",
    "aircraft_type":    "TEXT",
    "operator":         "TEXT",
    "origin_code":      "TEXT",
    "destination_code": "TEXT",
    "altitude_ft":      "INTEGER",
    "ground_speed_mph": "INTEGER",
    "flight_status":    "TEXT",
    "image_path":       "TEXT",
}


def ensure_events_aircraft_columns(conn: sqlite3.Connection) -> dict[str, bool]:
    """
    Add FR24 aircraft-detail columns to the events table if absent.

    Returns a dict mapping column name → True if it was added on this call,
    False if it was already present.
    """
    if "events" not in _existing_tables(conn):
        # Fresh DB — schema_sqlite.sql already defines the columns.
        return {col: False for col in _EVENTS_AIRCRAFT_COLUMNS}
    added = {
        col: _add_column_if_missing(conn, "events", col, col_type)
        for col, col_type in _EVENTS_AIRCRAFT_COLUMNS.items()
    }
    conn.commit()
    return added


def ensure_alerts_registration_column(conn: sqlite3.Connection) -> dict[str, bool]:
    """
    Add a registration TEXT column to the alerts table if absent, so aircraft
    watchlist alerts can be keyed and displayed by registration.
    """
    if "alerts" not in _existing_tables(conn):
        return {"registration": False}
    added = {"registration": _add_column_if_missing(conn, "alerts", "registration", "TEXT")}
    conn.commit()
    return added


def ensure_track_points_table(conn: sqlite3.Connection) -> bool:
    """
    Create the track_points table if absent (per-point ADS-B tracks linked to
    events.id). CREATE TABLE IF NOT EXISTS is idempotent, so this is safe on
    every startup. Returns True if the table did not previously exist.

    Keep this in sync with server/database/schema_sqlite.sql.
    """
    created = "track_points" not in _existing_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS track_points (
            flight_id    TEXT    NOT NULL,
            ts           INTEGER NOT NULL,
            at           TEXT,
            lat          REAL,
            lng          REAL,
            altitude_ft  INTEGER,
            speed        INTEGER,
            direction    INTEGER,
            PRIMARY KEY (flight_id, ts)
        )
        """
    )
    conn.commit()
    return created


def run_all(conn: sqlite3.Connection) -> dict[str, dict]:
    """Run every registered migration. Safe to call on every startup."""
    return {
        "sites_geoid": ensure_sites_geoid_columns(conn),
        "events_aircraft": ensure_events_aircraft_columns(conn),
        "alerts_registration": ensure_alerts_registration_column(conn),
        "track_points": {"created": ensure_track_points_table(conn)},
    }


__all__ = [
    "ensure_sites_geoid_columns",
    "ensure_events_aircraft_columns",
    "ensure_alerts_registration_column",
    "ensure_track_points_table",
    "run_all",
]
