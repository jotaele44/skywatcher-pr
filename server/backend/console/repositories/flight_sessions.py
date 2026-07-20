"""Phase 2 flight sessions repository adapter."""

from __future__ import annotations

from .flight_common import *  # noqa: F403
from .tracks import TrackPointRepository

class FlightSessionRepository:
    name = "flight_sessions"

    def __init__(self, root: Path, track_repository: TrackPointRepository | None = None):
        self.root = root
        self.track_repository = track_repository or TrackPointRepository(root)

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        skipped = 0
        candidates = _db_candidates(self.root)
        candidates += _structured_candidates(self.root, "SKYWATCHER_FLIGHT_SESSIONS", FUSED_FLIGHT_DEFAULTS)
        seen: set[str] = set()
        for path, configured_by in candidates:
            key = str(path.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="flight_sessions", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    loaded, rejected = self._from_database(path)
                    kind = "sqlite_flights"
                else:
                    loaded, rejected = self._from_structured(path)
                    kind = "structured_flights"
                rows.extend(loaded)
                skipped += rejected
                artifacts.append(artifact_ref(path, kind=kind, configured_by=configured_by, record_count=len(loaded), status="loaded"))
            except Exception as exc:
                artifacts.append(artifact_ref(path, kind="flight_sessions", configured_by=configured_by, status="error", error=f"{type(exc).__name__}: {exc}"))

        if not rows:
            derived = self._derive_from_tracks(self.track_repository.snapshot())
            if derived:
                rows.extend(derived)
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["flight_id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No bounded flight-session database or fused-flight artifact is present. "
                "Configure SKYWATCHER_FLIGHT_DB or SKYWATCHER_FLIGHT_SESSIONS."
            ),
            empty_reason="Flight artifacts exist but contain no UTC-valid sessions.",
            skipped_rows=skipped,
        )

    def _from_database(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        connection = open_sqlite_readonly(path)
        try:
            raw: list[dict[str, Any]] = []
            adapter = ""
            if sqlite_table_exists(connection, "console_flight_sessions"):
                raw = sqlite_rows(connection, "console_flight_sessions")
                adapter = "console_flight_sessions"
            if not raw and sqlite_table_exists(connection, "flights"):
                raw = sqlite_rows(connection, "flights")
                adapter = "legacy_flights"
            if not raw:
                return [], 0
            output: list[dict[str, Any]] = []
            rejected = 0
            for row in raw:
                value = self._normalize_session(row, path, adapter)
                if value is None:
                    rejected += 1
                else:
                    output.append(value)
            return output, rejected
        finally:
            connection.close()

    def _from_structured(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        output: list[dict[str, Any]] = []
        rejected = 0
        for row in read_structured_rows(path):
            value = self._normalize_session(row, path, "structured_flight_artifact")
            if value is None:
                rejected += 1
            else:
                output.append(value)
        return output, rejected

    def _normalize_session(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any] | None:
        qa_flags: list[str] = []
        first_seen = normalize_time(
            first(source, ("first_seen_at_utc", "first_seen_iso", "takeoff_time", "first_seen", "start_time")),
            field_name="first_seen_at_utc",
            qa_flags=qa_flags,
        )
        last_seen = normalize_time(
            first(source, ("last_seen_at_utc", "last_seen_iso", "landing_time", "last_seen", "end_time")),
            field_name="last_seen_at_utc",
            qa_flags=qa_flags,
        )
        if first_seen is None:
            points = source.get("points")
            if isinstance(points, list) and points:
                first_seen = normalize_time(first(points[0], ("timestamp_iso", "observed_at_utc", "timestamp")), field_name="first_seen_at_utc", qa_flags=qa_flags)
                last_seen = normalize_time(first(points[-1], ("timestamp_iso", "observed_at_utc", "timestamp")), field_name="last_seen_at_utc", qa_flags=qa_flags)
        if first_seen is None:
            return None
        last_seen = last_seen or first_seen
        aircraft_id = text(first(source, ("aircraft_id", "registration", "callsign", "callsign_or_label", "aircraft_identity")))
        if not aircraft_id:
            return None
        flight_id = text(first(source, ("flight_id", "candidate_id"))) or stable_id(path, aircraft_id, first_seen, last_seen, prefix="flight-")
        points = source.get("points") if isinstance(source.get("points"), list) else []
        point_count = as_int(source.get("point_count"))
        if point_count is None:
            point_count = len(points) or as_int(source.get("num_screenshots")) or 0
        is_console = adapter == "console_flight_sessions"
        synthetic = as_bool(source.get("synthetic") or source.get("synthetic_flag"))
        status = text(source.get("status")) or "unknown"
        if status not in {"active", "departed", "arrived", "completed", "unknown"}:
            qa_flags.append("unrecognized_flight_status")
            status = "unknown"
        track_quality = text(source.get("track_quality")) or ("sparse_evidence" if not is_console else "gapped")
        if track_quality not in {"continuous", "gapped", "sparse_evidence", "single_point"}:
            qa_flags.append("unrecognized_track_quality")
            track_quality = "sparse_evidence" if not is_console else "gapped"
        row = {
            "id": flight_id,
            "schema_version": "0.1.0",
            "flight_id": flight_id,
            "aircraft_id": aircraft_id,
            "icao24": text(source.get("icao24")) or None,
            "registration": text(source.get("registration")) or None,
            "callsign": text(first(source, ("callsign", "callsign_or_label"))) or None,
            "aircraft_type": text(source.get("aircraft_type")) or None,
            "operator": text(source.get("operator")) or None,
            "origin_airport_id": text(first(source, ("origin_airport_id", "origin_code", "origin"))) or None,
            "destination_airport_id": text(first(source, ("destination_airport_id", "destination_code", "destination"))) or None,
            "first_seen_at_utc": first_seen,
            "last_seen_at_utc": last_seen,
            "status": status,
            "point_count": point_count,
            "max_altitude_ft": as_float(source.get("max_altitude_ft")),
            "max_ground_speed_kt": as_float(source.get("max_ground_speed_kt")) or mph_to_kt(source.get("avg_speed_mph")),
            "track_quality": track_quality,
            "gap_count": as_int(source.get("gap_count")) or 0,
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"FlightSessionRepository:{adapter}",
            source_record_id=flight_id,
            source_family="operational_position" if is_console and not synthetic else "screenshot_evidence",
            source_provider="skywatcher-normalized-store" if is_console else "skywatcher-fr24-flight-fusion",
            source_method=text(source.get("source_method")) or ("database_import" if is_console else "derived_fusion"),
            data_rights=text(source.get("data_rights")) or ("owned" if is_console else "derived"),
            operational_mode=text(source.get("operational_mode")) or ("historical" if is_console else "evidence_only"),
            artifact_kind="flight_sessions",
            synthetic=synthetic,
            qa_flags=qa_flags,
        )

    def _derive_from_tracks(self, snapshot: RepositorySnapshot) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for point in snapshot.rows:
            flight_id = text(point.get("flight_id"))
            if flight_id:
                groups[flight_id].append(point)
        output: list[dict[str, Any]] = []
        for flight_id, points in groups.items():
            points.sort(key=lambda point: (point.get("observed_at_utc") or "", point.get("track_point_id") or ""))
            first_point, last_point = points[0], points[-1]
            synthetic = all(bool(point.get("synthetic")) for point in points)
            source_path = Path(first_point["provenance"]["artifact_path"])
            row = {
                "id": flight_id,
                "schema_version": "0.1.0",
                "flight_id": flight_id,
                "aircraft_id": first_point["aircraft_id"],
                "icao24": None,
                "registration": None,
                "callsign": None,
                "aircraft_type": None,
                "operator": None,
                "origin_airport_id": None,
                "destination_airport_id": None,
                "first_seen_at_utc": first_point["observed_at_utc"],
                "last_seen_at_utc": last_point["observed_at_utc"],
                "status": "unknown",
                "point_count": len(points),
                "max_altitude_ft": max((p.get("barometric_altitude_ft") for p in points if p.get("barometric_altitude_ft") is not None), default=None),
                "max_ground_speed_kt": max((p.get("ground_speed_kt") for p in points if p.get("ground_speed_kt") is not None), default=None),
                "track_quality": "single_point" if len(points) == 1 else "sparse_evidence",
                "gap_count": sum(1 for p in points if p.get("gap_before_seconds")),
            }
            output.append(
                attach_provenance(
                    row,
                    path=source_path,
                    adapter="FlightSessionRepository:derived_from_tracks",
                    source_record_id=flight_id,
                    source_family=first_point["provenance"]["source_family"],
                    source_provider="skywatcher-track-session-deriver",
                    source_method="derived_fusion",
                    data_rights="derived",
                    operational_mode=first_point["provenance"]["operational_mode"],
                    artifact_kind="derived_flight_session",
                    synthetic=synthetic,
                )
            )
        return output
