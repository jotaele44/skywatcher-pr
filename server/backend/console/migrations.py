"""Reversible SQLite migrations for console contracts.

Phase 1 creates only producer-owned normalized tables. Source artifacts remain
immutable. Rollback refuses to drop populated tables unless ``allow_data_loss``
is explicitly enabled.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .time import normalize_utc

MIGRATION_LEDGER_TABLE = "console_schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]
    down: Callable[[sqlite3.Connection, bool], None]
    checksum: str


def _execute_many(conn: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    for statement in statements:
        conn.execute(statement)


PHASE1_TABLES = (
    "console_aircraft_states",
    "console_track_points",
    "console_flight_sessions",
    "console_airport_operational_states",
)

_UP_V1 = (
    """
    CREATE TABLE IF NOT EXISTS console_aircraft_states (
        state_id TEXT PRIMARY KEY,
        aircraft_id TEXT NOT NULL,
        flight_id TEXT,
        observed_at_utc TEXT NOT NULL,
        lat REAL NOT NULL CHECK(lat BETWEEN -90 AND 90),
        lon REAL NOT NULL CHECK(lon BETWEEN -180 AND 180),
        barometric_altitude_ft REAL,
        geometric_altitude_ft REAL,
        ground_speed_kt REAL CHECK(ground_speed_kt IS NULL OR ground_speed_kt >= 0),
        vertical_rate_fpm REAL,
        track_deg REAL CHECK(track_deg IS NULL OR (track_deg >= 0 AND track_deg <= 360)),
        heading_deg REAL CHECK(heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 360)),
        squawk TEXT,
        on_ground INTEGER NOT NULL CHECK(on_ground IN (0, 1)),
        position_status TEXT NOT NULL,
        uncertainty_m REAL CHECK(uncertainty_m IS NULL OR uncertainty_m >= 0),
        confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        source_family TEXT NOT NULL,
        source_provider TEXT NOT NULL,
        source_method TEXT NOT NULL,
        data_rights TEXT NOT NULL,
        operational_mode TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        synthetic INTEGER NOT NULL CHECK(synthetic IN (0, 1)),
        qa_flags_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_console_states_time ON console_aircraft_states(observed_at_utc, state_id)",
    "CREATE INDEX IF NOT EXISTS idx_console_states_aircraft_time ON console_aircraft_states(aircraft_id, observed_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_console_states_bbox ON console_aircraft_states(lon, lat)",
    "CREATE INDEX IF NOT EXISTS idx_console_states_source ON console_aircraft_states(source_method, synthetic)",
    """
    CREATE TABLE IF NOT EXISTS console_track_points (
        track_point_id TEXT PRIMARY KEY,
        flight_id TEXT,
        aircraft_id TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        lat REAL NOT NULL CHECK(lat BETWEEN -90 AND 90),
        lon REAL NOT NULL CHECK(lon BETWEEN -180 AND 180),
        barometric_altitude_ft REAL,
        ground_speed_kt REAL CHECK(ground_speed_kt IS NULL OR ground_speed_kt >= 0),
        vertical_rate_fpm REAL,
        track_deg REAL CHECK(track_deg IS NULL OR (track_deg >= 0 AND track_deg <= 360)),
        measurement_status TEXT NOT NULL,
        interpolation_parent_ids_json TEXT NOT NULL DEFAULT '[]',
        segment_id TEXT,
        gap_before_seconds REAL CHECK(gap_before_seconds IS NULL OR gap_before_seconds >= 0),
        uncertainty_m REAL CHECK(uncertainty_m IS NULL OR uncertainty_m >= 0),
        confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        source_family TEXT NOT NULL,
        source_provider TEXT NOT NULL,
        source_method TEXT NOT NULL,
        data_rights TEXT NOT NULL,
        operational_mode TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        synthetic INTEGER NOT NULL CHECK(synthetic IN (0, 1))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_console_track_flight_time ON console_track_points(flight_id, observed_at_utc, track_point_id)",
    "CREATE INDEX IF NOT EXISTS idx_console_track_aircraft_time ON console_track_points(aircraft_id, observed_at_utc)",
    """
    CREATE TABLE IF NOT EXISTS console_flight_sessions (
        flight_id TEXT PRIMARY KEY,
        aircraft_id TEXT NOT NULL,
        icao24 TEXT,
        registration TEXT,
        callsign TEXT,
        aircraft_type TEXT,
        operator TEXT,
        origin_airport_id TEXT,
        destination_airport_id TEXT,
        first_seen_at_utc TEXT NOT NULL,
        last_seen_at_utc TEXT NOT NULL,
        status TEXT NOT NULL,
        point_count INTEGER NOT NULL DEFAULT 0 CHECK(point_count >= 0),
        max_altitude_ft REAL,
        max_ground_speed_kt REAL CHECK(max_ground_speed_kt IS NULL OR max_ground_speed_kt >= 0),
        track_quality TEXT NOT NULL,
        gap_count INTEGER NOT NULL DEFAULT 0 CHECK(gap_count >= 0),
        source_family TEXT NOT NULL,
        source_provider TEXT NOT NULL,
        source_method TEXT NOT NULL,
        data_rights TEXT NOT NULL,
        operational_mode TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        synthetic INTEGER NOT NULL CHECK(synthetic IN (0, 1))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_console_flights_time ON console_flight_sessions(first_seen_at_utc, flight_id)",
    "CREATE INDEX IF NOT EXISTS idx_console_flights_aircraft ON console_flight_sessions(aircraft_id, last_seen_at_utc)",
    """
    CREATE TABLE IF NOT EXISTS console_airport_operational_states (
        airport_state_id TEXT PRIMARY KEY,
        airport_id TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        operational_status TEXT NOT NULL,
        departures_count INTEGER CHECK(departures_count IS NULL OR departures_count >= 0),
        arrivals_count INTEGER CHECK(arrivals_count IS NULL OR arrivals_count >= 0),
        on_ground_count INTEGER CHECK(on_ground_count IS NULL OR on_ground_count >= 0),
        delay_minutes REAL CHECK(delay_minutes IS NULL OR delay_minutes >= 0),
        disruption_codes_json TEXT NOT NULL DEFAULT '[]',
        weather_json TEXT,
        events_json TEXT NOT NULL DEFAULT '[]',
        source_family TEXT NOT NULL,
        source_provider TEXT NOT NULL,
        source_method TEXT NOT NULL,
        data_rights TEXT NOT NULL,
        operational_mode TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        synthetic INTEGER NOT NULL CHECK(synthetic IN (0, 1))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_console_airport_state_time ON console_airport_operational_states(airport_id, observed_at_utc)",
)


def _up_v1(conn: sqlite3.Connection) -> None:
    _execute_many(conn, _UP_V1)


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _down_v1(conn: sqlite3.Connection, allow_data_loss: bool) -> None:
    populated = {table: _table_row_count(conn, table) for table in PHASE1_TABLES if _table_exists(conn, table)}
    populated = {table: count for table, count in populated.items() if count}
    if populated and not allow_data_loss:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(populated.items()))
        raise RuntimeError(f"rollback would discard console data: {detail}")
    for table in reversed(PHASE1_TABLES):
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')


def _checksum(statements: tuple[str, ...]) -> str:
    text = "\n".join(statement.strip() for statement in statements)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


MIGRATIONS = (
    Migration(1, "phase1_console_contract_tables", _up_v1, _down_v1, _checksum(_UP_V1)),
)
LATEST_VERSION = MIGRATIONS[-1].version


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def ensure_migration_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_LEDGER_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL
        )
        """
    )


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    ensure_migration_ledger(conn)
    return [int(row[0]) for row in conn.execute(
        f"SELECT version FROM {MIGRATION_LEDGER_TABLE} ORDER BY version"
    )]


def migration_ledger(conn: sqlite3.Connection) -> list[dict[str, str | int]]:
    ensure_migration_ledger(conn)
    rows = conn.execute(
        f"SELECT version, name, checksum, applied_at_utc FROM {MIGRATION_LEDGER_TABLE} ORDER BY version"
    ).fetchall()
    return [
        {"version": row[0], "name": row[1], "checksum": row[2], "applied_at_utc": row[3]}
        for row in rows
    ]


def migrate(conn: sqlite3.Connection, *, target_version: int = LATEST_VERSION) -> list[dict[str, str | int]]:
    if target_version < 0 or target_version > LATEST_VERSION:
        raise ValueError(f"target_version must be between 0 and {LATEST_VERSION}")
    ensure_migration_ledger(conn)
    current = max(applied_versions(conn), default=0)
    if target_version < current:
        return rollback(conn, target_version=target_version)

    for migration in MIGRATIONS:
        if current < migration.version <= target_version:
            with conn:
                migration.up(conn)
                conn.execute(
                    f"INSERT INTO {MIGRATION_LEDGER_TABLE}(version, name, checksum, applied_at_utc) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, normalize_utc(datetime.now(timezone.utc))),
                )
    return migration_ledger(conn)


def rollback(
    conn: sqlite3.Connection,
    *,
    target_version: int = 0,
    allow_data_loss: bool = False,
) -> list[dict[str, str | int]]:
    if target_version < 0 or target_version > LATEST_VERSION:
        raise ValueError(f"target_version must be between 0 and {LATEST_VERSION}")
    ensure_migration_ledger(conn)
    current_versions = set(applied_versions(conn))
    for migration in reversed(MIGRATIONS):
        if migration.version in current_versions and migration.version > target_version:
            with conn:
                migration.down(conn, allow_data_loss)
                conn.execute(
                    f"DELETE FROM {MIGRATION_LEDGER_TABLE} WHERE version=?", (migration.version,)
                )
    return migration_ledger(conn)
