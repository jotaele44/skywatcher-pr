"""Phase 2 airport states repository adapter."""

from __future__ import annotations

from .flight_common import *  # noqa: F403

class AirportStateRepository:
    name = "airport_operational_states"

    def __init__(self, root: Path):
        self.root = root

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        skipped = 0
        candidates = _db_candidates(self.root)
        candidates += _structured_candidates(self.root, "SKYWATCHER_AIRPORT_STATES", AIRPORT_STATE_DEFAULTS)
        seen: set[str] = set()
        for path, configured_by in candidates:
            key = str(path.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="airport_operational_states", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    raw = _table_rows(path, "console_airport_operational_states")
                    adapter = "console_airport_operational_states"
                else:
                    raw = read_structured_rows(path)
                    adapter = "structured_airport_states"
                loaded: list[dict[str, Any]] = []
                for source in raw:
                    value = self._normalize(source, path, adapter)
                    if value is None:
                        skipped += 1
                    else:
                        loaded.append(value)
                rows.extend(loaded)
                artifacts.append(artifact_ref(path, kind="airport_operational_states", configured_by=configured_by, record_count=len(loaded), status="loaded"))
            except Exception as exc:
                artifacts.append(artifact_ref(path, kind="airport_operational_states", configured_by=configured_by, status="error", error=f"{type(exc).__name__}: {exc}"))
        return finalize_snapshot(
            self.name,
            rows,
            artifacts,
            absent_reason=(
                "No owned, licensed, or public-official airport operational-state artifact is configured. "
                "Configure SKYWATCHER_AIRPORT_STATES or populate console_airport_operational_states."
            ),
            empty_reason="Airport-state artifacts exist but contain no UTC-valid records.",
            skipped_rows=skipped,
        )

    def _normalize(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any] | None:
        qa_flags: list[str] = []
        observed = normalize_time(
            first(source, ("observed_at_utc", "observed_at", "timestamp")),
            field_name="observed_at_utc",
            qa_flags=qa_flags,
        )
        airport_id = text(first(source, ("airport_id", "icao", "iata", "faa_code")))
        if observed is None or not airport_id:
            return None
        state_id = text(source.get("airport_state_id")) or stable_id(path, airport_id, observed, prefix="airport-state-")
        synthetic = as_bool(source.get("synthetic"))
        operational_status = text(source.get("operational_status")) or "unknown"
        if operational_status not in {"normal", "limited", "disrupted", "closed", "unknown"}:
            qa_flags.append("unrecognized_airport_operational_status")
            operational_status = "unknown"
        row = {
            "id": state_id,
            "schema_version": "0.1.0",
            "airport_state_id": state_id,
            "airport_id": airport_id,
            "observed_at_utc": observed,
            "operational_status": operational_status,
            "departures_count": as_int(source.get("departures_count")),
            "arrivals_count": as_int(source.get("arrivals_count")),
            "on_ground_count": as_int(source.get("on_ground_count")),
            "delay_minutes": as_float(source.get("delay_minutes")),
            "disruption_codes": parse_json(source.get("disruption_codes_json") or source.get("disruption_codes"), []),
            "weather": parse_json(source.get("weather_json") or source.get("weather"), None),
            "events": parse_json(source.get("events_json") or source.get("events"), []),
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"AirportStateRepository:{adapter}",
            source_record_id=state_id,
            source_family=text(source.get("source_family")) or "official_record",
            source_provider=text(source.get("source_provider")) or "configured-airport-state-provider",
            source_method=text(source.get("source_method")) or "airport_operations",
            data_rights=text(source.get("data_rights")) or "unknown",
            operational_mode=text(source.get("operational_mode")) or "historical",
            artifact_kind="airport_operational_states",
            synthetic=synthetic,
            qa_flags=qa_flags,
        )
