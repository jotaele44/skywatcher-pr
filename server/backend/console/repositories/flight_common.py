"""Aircraft-state, flight-session, track-point, route, and airport-state adapters."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import ArtifactRef, RepositorySnapshot, finalize_snapshot
from .capture_review import FLIGHT_DB_DEFAULTS
from .io import (
    artifact_ref,
    bounded_paths,
    open_sqlite_readonly,
    read_csv_rows,
    read_structured_rows,
    sqlite_columns,
    sqlite_rows,
    sqlite_table_exists,
)
from .normalize import (
    as_bool,
    as_float,
    as_int,
    attach_provenance,
    first,
    mph_to_kt,
    normalize_time,
    parse_json,
    stable_id,
    text,
)

FUSED_FLIGHT_DEFAULTS = (
    "data/_manifests/fr24_audit/fr24_fused_flights.json",
    "data/_manifests/fr24_audit/fused_flights.json",
    "reports/fr24/fr24_fused_flights.json",
    "reports/fr24/fused_flights.jsonl",
    "fr24_fused_flights.json",
    "fused_flights.json",
)

TRACK_DEFAULTS = (
    "data/_manifests/fr24_audit/track_points.csv",
    "data/_manifests/fr24_audit/route_segments.csv",
    "reports/fr24/track_points.jsonl",
    "reports/fr24/route_segments.json",
)

AIRPORT_STATE_DEFAULTS = (
    "data/airport_operational_states.jsonl",
    "data/airport_operational_states.json",
    "reports/airport_operational_states.jsonl",
)

SYNTHETIC_OBSERVATION_PATH = "exports/examples/synthetic_airspace_package/observations.csv"


def _db_candidates(root: Path) -> list[tuple[Path, str | None]]:
    return bounded_paths(root, env_var="SKYWATCHER_FLIGHT_DB", defaults=FLIGHT_DB_DEFAULTS)


def _structured_candidates(root: Path, env_var: str, defaults: tuple[str, ...]) -> list[tuple[Path, str | None]]:
    return bounded_paths(root, env_var=env_var, defaults=defaults)


def _table_rows(path: Path, table: str) -> list[dict[str, Any]]:
    connection = open_sqlite_readonly(path)
    try:
        if not sqlite_table_exists(connection, table):
            return []
        return sqlite_rows(connection, table)
    finally:
        connection.close()


__all__ = [
    "defaultdict",
    "Path",
    "Any",
    "ArtifactRef",
    "RepositorySnapshot",
    "finalize_snapshot",
    "FLIGHT_DB_DEFAULTS",
    "artifact_ref",
    "bounded_paths",
    "open_sqlite_readonly",
    "read_csv_rows",
    "read_structured_rows",
    "sqlite_columns",
    "sqlite_rows",
    "sqlite_table_exists",
    "as_bool",
    "as_float",
    "as_int",
    "attach_provenance",
    "first",
    "mph_to_kt",
    "normalize_time",
    "parse_json",
    "stable_id",
    "text",
    "FUSED_FLIGHT_DEFAULTS",
    "TRACK_DEFAULTS",
    "AIRPORT_STATE_DEFAULTS",
    "SYNTHETIC_OBSERVATION_PATH",
    "_db_candidates",
    "_structured_candidates",
    "_table_rows",
]
