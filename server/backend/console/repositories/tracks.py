"""Phase 2 tracks repository adapter."""

from __future__ import annotations

from .flight_common import *  # noqa: F403

class TrackPointRepository:
    name = "track_points"

    def __init__(self, root: Path):
        self.root = root

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        warnings: list[str] = []
        skipped = 0

        candidates = _db_candidates(self.root)
        candidates += _structured_candidates(
            self.root, "SKYWATCHER_TRACK_ARTIFACT", TRACK_DEFAULTS + FUSED_FLIGHT_DEFAULTS
        )
        seen: set[str] = set()
        for path, configured_by in candidates:
            key = str(path.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="track_artifact", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    loaded, rejected = self._from_database(path)
                    kind = "sqlite_track_points"
                else:
                    loaded, rejected = self._from_structured(path)
                    kind = "structured_track_points"
                rows.extend(loaded)
                skipped += rejected
                artifacts.append(
                    artifact_ref(
                        path,
                        kind=kind,
                        configured_by=configured_by,
                        record_count=len(loaded),
                        status="loaded" if not rejected else "loaded_with_rejections",
                    )
                )
            except Exception as exc:
                artifacts.append(
                    artifact_ref(
                        path,
                        kind="track_artifact",
                        configured_by=configured_by,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        if skipped:
            warnings.append(f"{skipped} track rows rejected because required UTC/geometry fields were invalid")
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["track_point_id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No bounded normalized-track database or fused-flight artifact is present. "
                "Configure SKYWATCHER_FLIGHT_DB or SKYWATCHER_TRACK_ARTIFACT."
            ),
            empty_reason="Track artifacts exist but contain no UTC-valid geospatial points.",
            warnings=warnings,
            skipped_rows=skipped,
        )

    def _from_database(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        connection = open_sqlite_readonly(path)
        try:
            source_rows: list[dict[str, Any]] = []
            adapter = ""
            if sqlite_table_exists(connection, "console_track_points"):
                source_rows = sqlite_rows(connection, "console_track_points")
                adapter = "console_track_points"
            if not source_rows and sqlite_table_exists(connection, "track_points"):
                source_rows = sqlite_rows(connection, "track_points")
                adapter = "legacy_track_points"
            if not source_rows:
                return [], 0
            normalized: list[dict[str, Any]] = []
            rejected = 0
            for row in source_rows:
                value = self._normalize_point(row, path, adapter)
                if value is None:
                    rejected += 1
                else:
                    normalized.append(value)
            return normalized, rejected
        finally:
            connection.close()

    def _from_structured(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        raw = read_structured_rows(path)
        points: list[dict[str, Any]] = []
        for row in raw:
            nested = row.get("points")
            if isinstance(nested, list):
                flight_id = text(first(row, ("flight_id", "candidate_id", "aircraft_identity")))
                aircraft_id = text(first(row, ("aircraft_id", "registration", "callsign", "aircraft_identity")))
                for index, point in enumerate(nested):
                    if not isinstance(point, dict):
                        continue
                    merged = dict(point)
                    merged.setdefault("flight_id", flight_id)
                    merged.setdefault("aircraft_id", aircraft_id)
                    merged.setdefault("point_index", index)
                    points.append(merged)
            else:
                points.append(row)
        normalized: list[dict[str, Any]] = []
        rejected = 0
        for row in points:
            value = self._normalize_point(row, path, "structured_track_artifact")
            if value is None:
                rejected += 1
            else:
                normalized.append(value)
        return normalized, rejected

    def _normalize_point(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any] | None:
        qa_flags: list[str] = []
        observed = normalize_time(
            first(source, ("observed_at_utc", "timestamp_iso", "vector_playback_iso", "timestamp", "event_datetime")),
            field_name="observed_at_utc",
            qa_flags=qa_flags,
        )
        lat = as_float(first(source, ("lat", "latitude")))
        lon = as_float(first(source, ("lon", "longitude")))
        if observed is None or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        source_id = text(first(source, ("track_point_id", "id", "source_record_id")))
        flight_id = text(first(source, ("flight_id", "candidate_id"))) or None
        aircraft_id = text(first(source, ("aircraft_id", "registration", "callsign", "aircraft_identity")))
        if not aircraft_id:
            aircraft_id = f"unknown::{flight_id or 'unassigned'}"
            qa_flags.append("aircraft_identity_unresolved")
        track_point_id = source_id or stable_id(path, flight_id, aircraft_id, observed, lat, lon, source.get("point_index"), prefix="tp-")
        is_console = adapter == "console_track_points"
        if adapter == "legacy_track_points":
            qa_flags.append("legacy_screenshot_route_export")
            if as_float(source.get("altitude_ft")) == 0 and as_float(source.get("ground_speed_mph")) == 0:
                qa_flags.append("legacy_zero_defaults_possible")
        speed_kt = as_float(source.get("ground_speed_kt"))
        if speed_kt is None:
            speed_kt = mph_to_kt(source.get("ground_speed_mph"))
        measurement_status = text(source.get("measurement_status"))
        if measurement_status not in {"measured", "derived_from_screenshot", "interpolated_for_display"}:
            measurement_status = "measured" if is_console else "derived_from_screenshot"
        synthetic = as_bool(source.get("synthetic") or source.get("synthetic_flag"))
        track_deg = as_float(first(source, ("track_deg", "heading_deg", "bearing")))
        if track_deg is not None and not (0 <= track_deg <= 360):
            qa_flags.append("track_deg_out_of_range")
            track_deg = None
        row = {
            "id": track_point_id,
            "schema_version": "0.1.0",
            "track_point_id": track_point_id,
            "flight_id": flight_id,
            "aircraft_id": aircraft_id,
            "observed_at_utc": observed,
            "lat": lat,
            "lon": lon,
            "barometric_altitude_ft": as_float(first(source, ("barometric_altitude_ft", "altitude_ft"))),
            "ground_speed_kt": speed_kt,
            "vertical_rate_fpm": as_float(source.get("vertical_rate_fpm")),
            "track_deg": track_deg,
            "measurement_status": measurement_status,
            "interpolation_parent_ids": parse_json(source.get("interpolation_parent_ids_json") or source.get("interpolation_parent_ids"), []),
            "segment_id": text(source.get("segment_id")) or None,
            "gap_before_seconds": as_float(source.get("gap_before_seconds")),
            "uncertainty_m": as_float(first(source, ("uncertainty_m", "estimated_error_m"))),
            "confidence": as_float(first(source, ("confidence", "coordinate_confidence"))),
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"TrackPointRepository:{adapter}",
            source_record_id=track_point_id,
            source_family="operational_position" if is_console and not synthetic else "screenshot_evidence",
            source_provider="skywatcher-normalized-store" if is_console else "skywatcher-fr24-route-extraction",
            source_method=text(source.get("source_method")) or ("database_import" if is_console else "track_extraction"),
            data_rights=text(source.get("data_rights")) or ("owned" if is_console else "derived"),
            operational_mode=text(source.get("operational_mode")) or ("historical" if is_console else "evidence_only"),
            artifact_kind="track_points",
            synthetic=synthetic,
            qa_flags=qa_flags,
        )
