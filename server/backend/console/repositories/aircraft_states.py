"""Phase 2 aircraft states repository adapter."""

from __future__ import annotations

from .flight_common import *  # noqa: F403
from .tracks import TrackPointRepository

class AircraftStateRepository:
    name = "aircraft_states"

    def __init__(self, root: Path, track_repository: TrackPointRepository | None = None):
        self.root = root
        self.track_repository = track_repository or TrackPointRepository(root)

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        skipped = 0
        for path, configured_by in _db_candidates(self.root):
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="aircraft_states", configured_by=configured_by))
                continue
            try:
                raw = _table_rows(path, "console_aircraft_states")
                loaded: list[dict[str, Any]] = []
                rejected = 0
                for row in raw:
                    normalized = self._normalize_state(row, path, "console_aircraft_states")
                    if normalized is None:
                        rejected += 1
                    else:
                        loaded.append(normalized)
                rows.extend(loaded)
                skipped += rejected
                artifacts.append(artifact_ref(path, kind="sqlite_aircraft_states", configured_by=configured_by, record_count=len(loaded), status="loaded"))
            except Exception as exc:
                artifacts.append(artifact_ref(path, kind="aircraft_states", configured_by=configured_by, status="error", error=f"{type(exc).__name__}: {exc}"))

        if not rows:
            track_snapshot = self.track_repository.snapshot()
            latest: dict[str, dict[str, Any]] = {}
            for point in track_snapshot.rows:
                aircraft_id = str(point["aircraft_id"])
                current = latest.get(aircraft_id)
                if current is None or (point["observed_at_utc"], point["track_point_id"]) > (current["observed_at_utc"], current["track_point_id"]):
                    latest[aircraft_id] = point
            for point in latest.values():
                rows.append(self._state_from_track(point))

        synthetic_path = self.root / SYNTHETIC_OBSERVATION_PATH
        if not rows and synthetic_path.is_file():
            loaded: list[dict[str, Any]] = []
            for source in read_csv_rows(synthetic_path):
                normalized = self._from_observation(source, synthetic_path)
                if normalized is None:
                    skipped += 1
                else:
                    loaded.append(normalized)
            rows.extend(loaded)
            artifacts.append(artifact_ref(synthetic_path, kind="synthetic_observations", record_count=len(loaded), status="loaded"))

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["state_id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No normalized aircraft-state artifact is available. "
                "Configure SKYWATCHER_FLIGHT_DB or provide track artifacts."
            ),
            empty_reason="Aircraft-state artifacts exist but contain no UTC-valid positions.",
            skipped_rows=skipped,
        )

    def _normalize_state(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any] | None:
        qa_flags: list[str] = []
        observed = normalize_time(source.get("observed_at_utc"), field_name="observed_at_utc", qa_flags=qa_flags)
        lat = as_float(source.get("lat"))
        lon = as_float(source.get("lon"))
        aircraft_id = text(source.get("aircraft_id"))
        if observed is None or lat is None or lon is None or not aircraft_id:
            return None
        state_id = text(source.get("state_id")) or stable_id(path, aircraft_id, observed, lat, lon, prefix="state-")
        synthetic = as_bool(source.get("synthetic"))
        position_status = text(source.get("position_status")) or "measured"
        if position_status not in {"measured", "stale_hold", "interpolated", "approximate"}:
            qa_flags.append("unrecognized_position_status")
            position_status = "approximate"
        squawk = text(source.get("squawk")) or None
        if squawk is not None and (len(squawk) != 4 or any(character not in "01234567" for character in squawk)):
            qa_flags.append("invalid_squawk")
            squawk = None
        row = {
            "id": state_id,
            "schema_version": "0.1.0",
            "state_id": state_id,
            "aircraft_id": aircraft_id,
            "flight_id": text(source.get("flight_id")) or None,
            "observed_at_utc": observed,
            "lat": lat,
            "lon": lon,
            "barometric_altitude_ft": as_float(source.get("barometric_altitude_ft")),
            "geometric_altitude_ft": as_float(source.get("geometric_altitude_ft")),
            "ground_speed_kt": as_float(source.get("ground_speed_kt")),
            "vertical_rate_fpm": as_float(source.get("vertical_rate_fpm")),
            "track_deg": as_float(source.get("track_deg")),
            "heading_deg": as_float(source.get("heading_deg")),
            "squawk": squawk,
            "on_ground": as_bool(source.get("on_ground")),
            "position_status": position_status,
            "state_age_seconds": as_float(source.get("state_age_seconds")),
            "uncertainty_m": as_float(source.get("uncertainty_m")),
            "confidence": as_float(source.get("confidence")),
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"AircraftStateRepository:{adapter}",
            source_record_id=state_id,
            source_family=text(source.get("source_family")) or "operational_position",
            source_provider=text(source.get("source_provider")) or "skywatcher-normalized-store",
            source_method=text(source.get("source_method")) or "database_import",
            data_rights=text(source.get("data_rights")) or "owned",
            operational_mode=text(source.get("operational_mode")) or "historical",
            artifact_kind="aircraft_states",
            synthetic=synthetic,
            qa_flags=qa_flags,
        )

    def _state_from_track(self, point: dict[str, Any]) -> dict[str, Any]:
        state_id = stable_id("track-latest", point["track_point_id"], prefix="state-")
        row = {
            "id": state_id,
            "schema_version": "0.1.0",
            "state_id": state_id,
            "aircraft_id": point["aircraft_id"],
            "flight_id": point.get("flight_id"),
            "observed_at_utc": point["observed_at_utc"],
            "lat": point["lat"],
            "lon": point["lon"],
            "barometric_altitude_ft": point.get("barometric_altitude_ft"),
            "geometric_altitude_ft": None,
            "ground_speed_kt": point.get("ground_speed_kt"),
            "vertical_rate_fpm": point.get("vertical_rate_fpm"),
            "track_deg": point.get("track_deg"),
            "heading_deg": None,
            "squawk": None,
            "on_ground": False,
            "position_status": "approximate" if point["measurement_status"] != "measured" else "measured",
            "state_age_seconds": None,
            "uncertainty_m": point.get("uncertainty_m"),
            "confidence": point.get("confidence"),
        }
        source_path = Path(point["provenance"]["artifact_path"])
        return attach_provenance(
            row,
            path=source_path,
            adapter="AircraftStateRepository:latest_track_point",
            source_record_id=state_id,
            source_family=point["provenance"]["source_family"],
            source_provider="skywatcher-track-state-deriver",
            source_method=point["provenance"]["source_method"],
            data_rights="derived",
            operational_mode=point["provenance"]["operational_mode"],
            artifact_kind="derived_aircraft_state",
            synthetic=bool(point.get("synthetic")),
            qa_flags=list(point.get("qa_flags") or []),
        )

    def _from_observation(self, source: dict[str, Any], path: Path) -> dict[str, Any] | None:
        qa_flags: list[str] = []
        observed = normalize_time(source.get("event_datetime"), field_name="event_datetime", qa_flags=qa_flags)
        lat = as_float(source.get("lat"))
        lon = as_float(source.get("lon"))
        if observed is None or lat is None or lon is None:
            return None
        observation_id = text(source.get("observation_id")) or stable_id(path, source, prefix="obs-")
        aircraft_id = text(first(source, ("aircraft_id", "registration", "callsign"))) or f"synthetic::{observation_id}"
        row = {
            "id": observation_id,
            "schema_version": "0.1.0",
            "state_id": observation_id,
            "aircraft_id": aircraft_id,
            "flight_id": None,
            "observed_at_utc": observed,
            "lat": lat,
            "lon": lon,
            "barometric_altitude_ft": as_float(source.get("altitude_ft")),
            "geometric_altitude_ft": None,
            "ground_speed_kt": None,
            "vertical_rate_fpm": None,
            "track_deg": as_float(source.get("bearing")),
            "heading_deg": None,
            "squawk": None,
            "on_ground": False,
            "position_status": "approximate",
            "state_age_seconds": None,
            "uncertainty_m": None,
            "confidence": as_float(source.get("confidence")),
        }
        return attach_provenance(
            row,
            path=path,
            adapter="AircraftStateRepository:synthetic_observation_fixture",
            source_record_id=observation_id,
            source_family="synthetic_test",
            source_provider="skywatcher-synthetic-export",
            source_method="database_import",
            data_rights="synthetic",
            operational_mode="batch",
            artifact_kind="synthetic_observation",
            synthetic=True,
            qa_flags=qa_flags + ["synthetic_fixture_not_operational"],
        )
