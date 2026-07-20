"""Aircraft profile artifact adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import ArtifactRef, RepositorySnapshot, finalize_snapshot
from .capture_review import FLIGHT_DB_DEFAULTS
from .io import (
    artifact_ref,
    bounded_paths,
    open_sqlite_readonly,
    read_structured_rows,
    sqlite_rows,
    sqlite_table_exists,
)
from .normalize import (
    as_bool,
    as_float,
    as_int,
    attach_provenance,
    first,
    normalize_time,
    parse_json,
    stable_id,
    text,
)

PROFILE_DEFAULTS = (
    "data/aircraft_profiles.json",
    "data/aircraft_profiles.jsonl",
    "reports/aircraft_profiles.json",
    "reports/aircraft_profiles.jsonl",
    "exports/aircraft_profiles.json",
    "exports/aircraft_profiles.jsonl",
)


class AircraftProfileRepository:
    name = "aircraft_profiles"

    def __init__(self, root: Path):
        self.root = root

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        skipped = 0
        candidates = bounded_paths(
            self.root,
            env_var="SKYWATCHER_AIRCRAFT_PROFILES",
            defaults=PROFILE_DEFAULTS,
        )
        candidates += bounded_paths(
            self.root,
            env_var="SKYWATCHER_FLIGHT_DB",
            defaults=FLIGHT_DB_DEFAULTS,
        )
        seen: set[str] = set()
        for path, configured_by in candidates:
            key = str(path.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="aircraft_profiles", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    loaded = self._from_database(path)
                    kind = "sqlite_aircraft_profiles"
                else:
                    loaded = [self._normalize(row, path, "structured_aircraft_profiles") for row in read_structured_rows(path)]
                    kind = "structured_aircraft_profiles"
                eligible = [row for row in loaded if row is not None]
                skipped += len(loaded) - len(eligible)
                rows.extend(eligible)
                artifacts.append(
                    artifact_ref(
                        path,
                        kind=kind,
                        configured_by=configured_by,
                        record_count=len(eligible),
                        status="loaded",
                    )
                )
            except Exception as exc:
                artifacts.append(
                    artifact_ref(
                        path,
                        kind="aircraft_profiles",
                        configured_by=configured_by,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No bounded aircraft-profile database or export is present. "
                "Configure SKYWATCHER_AIRCRAFT_PROFILES or SKYWATCHER_FLIGHT_DB."
            ),
            empty_reason="Aircraft-profile artifacts exist but contain no identity rows.",
            skipped_rows=skipped,
        )

    def _from_database(self, path: Path) -> list[dict[str, Any] | None]:
        connection = open_sqlite_readonly(path)
        try:
            if not sqlite_table_exists(connection, "aircraft_profiles"):
                return []
            return [self._normalize(row, path, "sqlite_aircraft_profiles") for row in sqlite_rows(connection, "aircraft_profiles")]
        finally:
            connection.close()

    def _normalize(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any] | None:
        identity = text(first(source, ("aircraft_id", "registration", "callsign", "tail_number", "icao24")))
        if not identity:
            return None
        profile_id = text(source.get("profile_id")) or stable_id(path, identity, prefix="profile-")
        qa_flags: list[str] = []
        first_seen = None
        last_seen = None
        if first(source, ("first_seen", "first_seen_at_utc")) not in (None, ""):
            first_seen = normalize_time(
                first(source, ("first_seen_at_utc", "first_seen")),
                field_name="first_seen_at_utc",
                qa_flags=qa_flags,
            )
        if first(source, ("last_seen", "last_seen_at_utc")) not in (None, ""):
            last_seen = normalize_time(
                first(source, ("last_seen_at_utc", "last_seen")),
                field_name="last_seen_at_utc",
                qa_flags=qa_flags,
            )
        data_source = text(source.get("data_source")) or "unknown"
        row = {
            "id": profile_id,
            "profile_id": profile_id,
            "aircraft_id": identity,
            "icao24": text(source.get("icao24")) or None,
            "registration": text(first(source, ("registration", "tail_number"))) or None,
            "callsign": text(source.get("callsign")) or None,
            "aircraft_type": text(first(source, ("aircraft_type", "type_code", "model"))) or None,
            "owner": text(source.get("owner")) or "Unknown",
            "operator": text(source.get("operator")) or "Unknown",
            "country": text(source.get("country")) or "Unknown",
            "primary_mission": text(source.get("primary_mission")) or "Unknown",
            "secondary_missions": parse_json(source.get("secondary_missions"), []),
            "confidence_level": as_float(first(source, ("confidence_level", "confidence"))),
            "operational_patterns": parse_json(source.get("operational_patterns"), {}),
            "total_flights": as_int(source.get("total_flights")) or 0,
            "first_seen_at_utc": first_seen,
            "last_seen_at_utc": last_seen,
            "data_source": data_source,
        }
        rights = "public_official" if data_source == "known_db" else "derived"
        return attach_provenance(
            row,
            path=path,
            adapter=f"AircraftProfileRepository:{adapter}",
            source_record_id=profile_id,
            source_family="official_record" if data_source == "known_db" else "secondary_reference",
            source_provider="skywatcher-aircraft-intelligence",
            source_method="aircraft_registry",
            data_rights=rights,
            operational_mode="batch",
            artifact_kind="aircraft_profiles",
            synthetic=as_bool(source.get("synthetic") or source.get("synthetic_flag")),
            qa_flags=qa_flags,
        )
