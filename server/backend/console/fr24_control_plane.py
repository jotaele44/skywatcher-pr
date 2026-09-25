"""Bridge FR24 control-plane CSV exports into Skywatcher console contracts.

The bridge is deliberately identity-preserving: callsign, registration, ICAO24,
and aircraft type remain separate source observations. Blank observations never
erase a prior nonblank value. Contradictory nonblank observations are retained
in provenance and leave the conflicting canonical field unresolved.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .migrations import migrate
from .time import UTCValidationError, normalize_utc


IDENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "aircraft_id": ("aircraft_id", "aircraft_identity"),
    "icao24": ("icao24", "hex", "hex_code", "mode_s", "transponder"),
    "registration": ("registration", "reg", "tail", "tail_number", "source_registration"),
    "callsign": ("callsign", "call_sign", "source_callsign"),
    "aircraft_type": ("aircraft_type", "aircraftType", "type_code", "typecode"),
}

FLIGHT_ID_ALIASES = ("flight_id", "fid", "id", "candidate_id")
POINT_ID_ALIASES = ("track_point_id", "point_id", "id", "source_record_id")
FIRST_SEEN_ALIASES = (
    "first_seen_at_utc",
    "first_seen_iso",
    "takeoff_time",
    "first_seen",
    "start_time",
    "t0",
)
LAST_SEEN_ALIASES = (
    "last_seen_at_utc",
    "last_seen_iso",
    "landing_time",
    "last_seen",
    "end_time",
    "t1",
)
POINT_TIME_ALIASES = (
    "observed_at_utc",
    "timestamp_iso",
    "utc",
    "timestamp",
    "time",
    "event_datetime",
)
LAT_ALIASES = ("lat", "latitude")
LON_ALIASES = ("lon", "lng", "longitude")
ALT_ALIASES = ("barometric_altitude_ft", "altitude_ft", "altitude", "alt")
SPEED_ALIASES = ("ground_speed_kt", "speed_kt", "groundspeed", "speed")
TRACK_ALIASES = ("track_deg", "heading_deg", "heading", "direction", "track")


@dataclass(frozen=True)
class BridgeSummary:
    flight_rows_input: int
    track_rows_input: int
    flight_sessions_written: int
    track_points_written: int
    rejected_flight_rows: int
    rejected_track_rows: int
    identity_conflict_flights: int
    unresolved_identity_flights: int
    identity_survival_failures: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(row: dict[str, Any], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = _text(row.get(alias))
        if value:
            return value
    return ""


def _float(value: Any) -> float | None:
    try:
        raw = _text(value)
        return float(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _utc(value: Any, *, field_name: str) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        epoch = float(raw)
    except ValueError:
        try:
            return normalize_utc(raw, field_name=field_name)
        except UTCValidationError:
            return None
    try:
        return (
            datetime.fromtimestamp(epoch, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: Any, prefix: str) -> str:
    payload = "|".join(_text(part) for part in parts)
    return prefix + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _add_identity(
    observations: dict[str, list[str]],
    row: dict[str, Any],
) -> None:
    for field_name, aliases in IDENTITY_ALIASES.items():
        for alias in aliases:
            value = _text(row.get(alias))
            if value and value not in observations[field_name]:
                observations[field_name].append(value)


def _existing_identity_observations(
    row: sqlite3.Row | None,
) -> dict[str, list[str]]:
    observations = {field: [] for field in IDENTITY_ALIASES}
    if row is None:
        return observations

    try:
        provenance = json.loads(row["provenance_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        provenance = {}
    carried = provenance.get("identity_observations")
    if isinstance(carried, dict):
        for field_name in observations:
            values = carried.get(field_name)
            if isinstance(values, list):
                for value in values:
                    normalized = _text(value)
                    if normalized and normalized not in observations[field_name]:
                        observations[field_name].append(normalized)

    for field_name in observations:
        if field_name in row.keys():
            value = _text(row[field_name])
            if value and value not in observations[field_name]:
                observations[field_name].append(value)
    return observations


def _canonical_identity(
    observations: dict[str, list[str]],
    flight_id: str,
) -> tuple[dict[str, str | None], str, list[str]]:
    canonical: dict[str, str | None] = {}
    conflicts: list[str] = []
    for field_name, values in observations.items():
        if len(values) == 1:
            canonical[field_name] = values[0]
        elif len(values) > 1:
            canonical[field_name] = None
            conflicts.append(field_name)
        else:
            canonical[field_name] = None

    aircraft_id = (
        canonical["aircraft_id"]
        or canonical["icao24"]
        or canonical["registration"]
        or canonical["callsign"]
        or f"unresolved::{flight_id}"
    )
    state = (
        "UNRESOLVED_CONFLICT"
        if conflicts
        else "SOURCE_IDENTITY_PRESENT"
        if aircraft_id != f"unresolved::{flight_id}"
        else "UNRESOLVED"
    )
    return canonical, state, conflicts


def _merge_existing_identity(
    observations: dict[str, list[str]],
    existing: sqlite3.Row | None,
) -> None:
    carried = _existing_identity_observations(existing)
    for field_name, values in carried.items():
        for value in values:
            if value not in observations[field_name]:
                observations[field_name].append(value)


def _artifact_provenance(
    path: Path,
    *,
    source_ref: str,
    artifact_kind: str,
) -> dict[str, Any]:
    return {
        "source_family": "operational_position",
        "source_provider": "fr24-control-plane",
        "source_method": "control_plane_export",
        "data_rights": "user_supplied",
        "operational_mode": "historical",
        "source_record_id": _sha256(path),
        "lineage_id": f"{source_ref}:{artifact_kind}",
        "artifact_path": str(path),
        "ingest_adapter": "FR24ControlPlaneBridge:rc4",
    }


def _upsert_artifact(
    conn: sqlite3.Connection,
    path: Path,
    *,
    source_ref: str,
    artifact_kind: str,
    record_count: int,
) -> None:
    digest = _sha256(path)
    artifact_id = _stable_id(source_ref, artifact_kind, digest, prefix="artifact-")
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    provenance = _artifact_provenance(path, source_ref=source_ref, artifact_kind=artifact_kind)
    conn.execute(
        """
        INSERT INTO console_source_artifacts(
          artifact_id, repository_name, artifact_kind, artifact_path, artifact_sha256,
          size_bytes, modified_at_utc, discovered_at_utc, availability_status,
          record_count, synthetic, provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(artifact_id) DO UPDATE SET
          artifact_path=excluded.artifact_path,
          artifact_sha256=excluded.artifact_sha256,
          size_bytes=excluded.size_bytes,
          modified_at_utc=excluded.modified_at_utc,
          discovered_at_utc=excluded.discovered_at_utc,
          availability_status=excluded.availability_status,
          record_count=excluded.record_count,
          provenance_json=excluded.provenance_json
        """,
        (
            artifact_id,
            "skywatcher-pr",
            artifact_kind,
            str(path),
            digest,
            path.stat().st_size,
            normalize_utc(modified),
            normalize_utc(datetime.now(timezone.utc)),
            "available",
            record_count,
            json.dumps(provenance, sort_keys=True, separators=(",", ":")),
        ),
    )


def ingest_fr24_control_plane(
    conn: sqlite3.Connection,
    *,
    flight_summary: Path,
    track_points: Path,
    source_ref: str = "FR24_14DAY_FETCH_V1_1.0.0rc4",
) -> BridgeSummary:
    """Load one FR24 control-plane export pair into normalized console tables."""

    migrate(conn)
    conn.row_factory = sqlite3.Row
    flight_rows = _read_csv(flight_summary)
    point_rows = _read_csv(track_points)

    grouped: dict[str, dict[str, Any]] = {}
    rejected_flight_rows = 0
    rejected_track_rows = 0

    for row in flight_rows:
        flight_id = _first(row, FLIGHT_ID_ALIASES)
        if not flight_id:
            rejected_flight_rows += 1
            continue
        item = grouped.setdefault(
            flight_id,
            {
                "flight_rows": [],
                "point_rows": [],
                "identity_observations": {field: [] for field in IDENTITY_ALIASES},
            },
        )
        item["flight_rows"].append(row)
        _add_identity(item["identity_observations"], row)

    for row in point_rows:
        flight_id = _first(row, FLIGHT_ID_ALIASES)
        if not flight_id:
            rejected_track_rows += 1
            continue
        item = grouped.setdefault(
            flight_id,
            {
                "flight_rows": [],
                "point_rows": [],
                "identity_observations": {field: [] for field in IDENTITY_ALIASES},
            },
        )
        item["point_rows"].append(row)
        _add_identity(item["identity_observations"], row)

    flight_sessions_written = 0
    track_points_written = 0
    identity_conflict_flights = 0
    unresolved_identity_flights = 0
    identity_survival_failures = 0

    for flight_id, item in sorted(grouped.items()):
        existing = conn.execute(
            "SELECT * FROM console_flight_sessions WHERE flight_id=?",
            (flight_id,),
        ).fetchone()
        observations = item["identity_observations"]
        _merge_existing_identity(observations, existing)
        canonical, identity_state, conflicts = _canonical_identity(observations, flight_id)
        if conflicts:
            identity_conflict_flights += 1
        if identity_state == "UNRESOLVED":
            unresolved_identity_flights += 1

        source_rows = item["flight_rows"]
        points = item["point_rows"]
        first_candidates: list[str] = []
        last_candidates: list[str] = []
        for row in source_rows:
            first_seen = _utc(_first(row, FIRST_SEEN_ALIASES), field_name="first_seen_at_utc")
            last_seen = _utc(_first(row, LAST_SEEN_ALIASES), field_name="last_seen_at_utc")
            if first_seen:
                first_candidates.append(first_seen)
            if last_seen:
                last_candidates.append(last_seen)
        for row in points:
            observed = _utc(_first(row, POINT_TIME_ALIASES), field_name="observed_at_utc")
            if observed:
                first_candidates.append(observed)
                last_candidates.append(observed)

        if existing is not None:
            first_candidates.append(_text(existing["first_seen_at_utc"]))
            last_candidates.append(_text(existing["last_seen_at_utc"]))
        first_seen = min(value for value in first_candidates if value) if first_candidates else None
        last_seen = max(value for value in last_candidates if value) if last_candidates else first_seen
        if first_seen is None or last_seen is None:
            rejected_flight_rows += max(1, len(source_rows))
            continue

        source = source_rows[0] if source_rows else {}
        status = _first(source, ("status",)).lower() or "unknown"
        if status not in {"active", "departed", "arrived", "completed", "unknown"}:
            status = "unknown"

        aircraft_id = (
            canonical["aircraft_id"]
            or canonical["icao24"]
            or canonical["registration"]
            or canonical["callsign"]
            or f"unresolved::{flight_id}"
        )
        max_altitude = max(
            (
                value
                for value in (
                    _float(_first(row, ALT_ALIASES)) for row in [*source_rows, *points]
                )
                if value is not None
            ),
            default=None,
        )
        max_speed = max(
            (
                value
                for value in (
                    _float(_first(row, SPEED_ALIASES)) for row in [*source_rows, *points]
                )
                if value is not None
            ),
            default=None,
        )
        provenance = {
            "source_family": "operational_position",
            "source_provider": "fr24-control-plane",
            "source_method": "control_plane_export",
            "data_rights": "user_supplied",
            "operational_mode": "historical",
            "source_record_id": flight_id,
            "lineage_id": f"{source_ref}:{flight_id}",
            "artifact_path": str(flight_summary),
            "ingest_adapter": "FR24ControlPlaneBridge:rc4",
            "source_identity": {
                field: _first(source, aliases) or None
                for field, aliases in IDENTITY_ALIASES.items()
            },
            "identity_observations": observations,
            "identity_state": identity_state,
            "identity_conflicts": conflicts,
        }

        conn.execute(
            """
            INSERT INTO console_flight_sessions(
              flight_id, aircraft_id, icao24, registration, callsign, aircraft_type,
              operator, origin_airport_id, destination_airport_id, first_seen_at_utc,
              last_seen_at_utc, status, point_count, max_altitude_ft,
              max_ground_speed_kt, track_quality, gap_count, source_family,
              source_provider, source_method, data_rights, operational_mode,
              source_record_id, lineage_id, provenance_json, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(flight_id) DO UPDATE SET
              aircraft_id=excluded.aircraft_id,
              icao24=excluded.icao24,
              registration=excluded.registration,
              callsign=excluded.callsign,
              aircraft_type=excluded.aircraft_type,
              operator=COALESCE(excluded.operator, console_flight_sessions.operator),
              origin_airport_id=COALESCE(
                excluded.origin_airport_id,
                console_flight_sessions.origin_airport_id
              ),
              destination_airport_id=COALESCE(
                excluded.destination_airport_id,
                console_flight_sessions.destination_airport_id
              ),
              first_seen_at_utc=MIN(
                excluded.first_seen_at_utc,
                console_flight_sessions.first_seen_at_utc
              ),
              last_seen_at_utc=MAX(
                excluded.last_seen_at_utc,
                console_flight_sessions.last_seen_at_utc
              ),
              status=excluded.status,
              point_count=MAX(excluded.point_count, console_flight_sessions.point_count),
              max_altitude_ft=MAX(excluded.max_altitude_ft, console_flight_sessions.max_altitude_ft),
              max_ground_speed_kt=MAX(
                excluded.max_ground_speed_kt,
                console_flight_sessions.max_ground_speed_kt
              ),
              track_quality=excluded.track_quality,
              gap_count=MAX(excluded.gap_count, console_flight_sessions.gap_count),
              provenance_json=excluded.provenance_json
            """,
            (
                flight_id,
                aircraft_id,
                canonical["icao24"],
                canonical["registration"],
                canonical["callsign"],
                canonical["aircraft_type"],
                _first(source, ("operator",)) or None,
                _first(source, ("origin_airport_id", "origin_code", "origin")) or None,
                _first(source, ("destination_airport_id", "destination_code", "destination")) or None,
                first_seen,
                last_seen,
                status,
                len(points),
                max_altitude,
                max_speed,
                "single_point" if len(points) == 1 else "gapped",
                _int(_first(source, ("gap_count",))) or 0,
                "operational_position",
                "fr24-control-plane",
                "control_plane_export",
                "user_supplied",
                "historical",
                flight_id,
                f"{source_ref}:{flight_id}",
                json.dumps(provenance, sort_keys=True, separators=(",", ":")),
            ),
        )
        flight_sessions_written += 1

        for index, row in enumerate(points):
            observed = _utc(_first(row, POINT_TIME_ALIASES), field_name="observed_at_utc")
            lat = _float(_first(row, LAT_ALIASES))
            lon = _float(_first(row, LON_ALIASES))
            if (
                observed is None
                or lat is None
                or lon is None
                or not (-90 <= lat <= 90)
                or not (-180 <= lon <= 180)
            ):
                rejected_track_rows += 1
                continue

            point_id = _first(row, POINT_ID_ALIASES) or _stable_id(
                source_ref,
                flight_id,
                observed,
                lat,
                lon,
                index,
                prefix="tp-",
            )
            point_identity = {field: list(values) for field, values in observations.items()}
            point_provenance = {
                "source_family": "operational_position",
                "source_provider": "fr24-control-plane",
                "source_method": "control_plane_export",
                "data_rights": "user_supplied",
                "operational_mode": "historical",
                "source_record_id": point_id,
                "lineage_id": f"{source_ref}:{flight_id}",
                "artifact_path": str(track_points),
                "ingest_adapter": "FR24ControlPlaneBridge:rc4",
                "source_identity": {
                    field: _first(row, aliases) or canonical[field]
                    for field, aliases in IDENTITY_ALIASES.items()
                },
                "identity_observations": point_identity,
                "identity_state": identity_state,
                "identity_conflicts": conflicts,
            }
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO console_track_points(
                  track_point_id, flight_id, aircraft_id, observed_at_utc, lat, lon,
                  barometric_altitude_ft, ground_speed_kt, vertical_rate_fpm,
                  track_deg, measurement_status, interpolation_parent_ids_json,
                  segment_id, gap_before_seconds, uncertainty_m, confidence,
                  source_family, source_provider, source_method, data_rights,
                  operational_mode, source_record_id, lineage_id, provenance_json,
                  synthetic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'measured', '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    point_id,
                    flight_id,
                    aircraft_id,
                    observed,
                    lat,
                    lon,
                    _float(_first(row, ALT_ALIASES)),
                    _float(_first(row, SPEED_ALIASES)),
                    _float(_first(row, ("vertical_rate_fpm", "vertical_rate"))),
                    _float(_first(row, TRACK_ALIASES)),
                    _first(row, ("segment_id",)) or None,
                    _float(_first(row, ("gap_before_seconds", "gap_seconds"))),
                    _float(_first(row, ("uncertainty_m", "estimated_error_m"))),
                    _float(_first(row, ("confidence", "coordinate_confidence"))),
                    "operational_position",
                    "fr24-control-plane",
                    "control_plane_export",
                    "user_supplied",
                    "historical",
                    point_id,
                    f"{source_ref}:{flight_id}",
                    json.dumps(point_provenance, sort_keys=True, separators=(",", ":")),
                ),
            )
            track_points_written += max(cursor.rowcount, 0)

        for field_name, aliases in IDENTITY_ALIASES.items():
            source_values = {
                _text(row.get(alias))
                for row in [*source_rows, *points]
                for alias in aliases
                if _text(row.get(alias))
            }
            if not source_values.issubset(set(observations[field_name])):
                identity_survival_failures += 1

    _upsert_artifact(
        conn,
        flight_summary,
        source_ref=source_ref,
        artifact_kind="fr24_control_plane_flight_summary",
        record_count=len(flight_rows),
    )
    _upsert_artifact(
        conn,
        track_points,
        source_ref=source_ref,
        artifact_kind="fr24_control_plane_track_points",
        record_count=len(point_rows),
    )
    conn.commit()

    return BridgeSummary(
        flight_rows_input=len(flight_rows),
        track_rows_input=len(point_rows),
        flight_sessions_written=flight_sessions_written,
        track_points_written=track_points_written,
        rejected_flight_rows=rejected_flight_rows,
        rejected_track_rows=rejected_track_rows,
        identity_conflict_flights=identity_conflict_flights,
        unresolved_identity_flights=unresolved_identity_flights,
        identity_survival_failures=identity_survival_failures,
    )
