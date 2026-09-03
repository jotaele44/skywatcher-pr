"""24-of-24 capability registry backed by Phase 2 repository snapshots."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .repositories import RepositoryRegistry
from .source_taxonomy import SOURCE_TAXONOMY_VERSION, build_provenance

API_VERSION = "0.3.0"
VALID_STATUSES = {
    "available",
    "available_synthetic_only",
    "unavailable_no_artifact",
    "unavailable_no_adapter",
    "disabled_by_policy",
    "degraded",
}
CAPABILITY_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"id": "airport_detail", "label": "Airport detail", "phase": 1, "status": "available", "reason": "Puerto Rico airport registry is loaded by the diagnostic backend."},
    {"id": "airport_operations", "label": "Airport operations", "phase": 7, "status": "unavailable_no_adapter", "reason": "No owned, licensed, or public-official operational adapter is configured."},
    {"id": "airport_disruptions", "label": "Airport disruptions", "phase": 7, "status": "unavailable_no_adapter", "reason": "No disruption adapter is configured."},
    {"id": "airport_weather", "label": "Airport weather", "phase": 7, "status": "unavailable_no_adapter", "reason": "No official METAR/TAF adapter is configured."},
    {"id": "bookmarks", "label": "Bookmarks", "phase": 4, "status": "unavailable_no_adapter", "reason": "Versioned diagnostic user-state repository is not implemented yet."},
    {"id": "recent_selections", "label": "Recent selections", "phase": 4, "status": "unavailable_no_adapter", "reason": "Console user-state repository is not implemented yet."},
    {"id": "view_modes", "label": "Map/list/airport/fleet view modes", "phase": 4, "status": "degraded", "reason": "The map console exists, while synchronized list, airport, and fleet modes remain future work."},
    {"id": "aircraft_viewport_list", "label": "Viewport aircraft list", "phase": 4, "status": "unavailable_no_artifact", "reason": "No normalized aircraft-state collection is connected."},
    {"id": "configurable_columns", "label": "Configurable columns", "phase": 4, "status": "unavailable_no_adapter", "reason": "Column registry is not implemented yet."},
    {"id": "map_navigation", "label": "Interactive map navigation", "phase": 3, "status": "available", "reason": "MapLibre GL JS navigation is available on /console with deterministic WebGL cleanup."},
    {"id": "geolocation", "label": "Geolocation", "phase": 3, "status": "available", "reason": "The /console runtime exposes a browser-permission-gated MapLibre geolocation control."},
    {"id": "playback_datetime", "label": "Playback date/time selection", "phase": 5, "status": "unavailable_no_artifact", "reason": "No UTC-valid time-indexed state repository is connected."},
    {"id": "playback_timeline", "label": "Playback timeline", "phase": 5, "status": "unavailable_no_artifact", "reason": "No normalized time-indexed track repository is connected."},
    {"id": "widgets", "label": "Console widgets", "phase": 6, "status": "degraded", "reason": "Diagnostic dashboard panels exist but are not dockable console widgets."},
    {"id": "basemap_controls", "label": "Basemap controls", "phase": 3, "status": "available", "reason": "The Phase 3 basemap registry includes a keyless local blank diagnostic style that requires no network."},
    {"id": "map_brightness", "label": "Map brightness", "phase": 3, "status": "unavailable_no_adapter", "reason": "Interactive map style brightness controls are not implemented yet."},
    {"id": "day_night_overlay", "label": "Day/night overlay", "phase": 6, "status": "unavailable_no_adapter", "reason": "Solar terminator layer is not implemented yet."},
    {"id": "atc_overlays", "label": "ATC overlays", "phase": 6, "status": "unavailable_no_artifact", "reason": "Authoritative display-ready ATC boundary layers are not connected."},
    {"id": "oceanic_tracks", "label": "Oceanic tracks", "phase": 6, "status": "unavailable_no_adapter", "reason": "No official or licensed oceanic-track adapter is configured."},
    {"id": "airport_badges", "label": "Airport badges", "phase": 6, "status": "unavailable_no_artifact", "reason": "Airport operational states are not connected."},
    {"id": "aircraft_labels", "label": "Aircraft labels", "phase": 6, "status": "unavailable_no_artifact", "reason": "Aircraft profile outputs are not connected."},
    {"id": "aircraft_styling", "label": "Aircraft styling", "phase": 6, "status": "unavailable_no_adapter", "reason": "Interactive aircraft symbol renderer is not implemented yet."},
    {"id": "source_visibility", "label": "Source visibility", "phase": 1, "status": "degraded", "reason": "Canonical taxonomy exists, but source-backed repositories are incomplete."},
    {"id": "unit_preferences", "label": "Unit preferences", "phase": 4, "status": "unavailable_no_adapter", "reason": "Unit provider and preference repository is not implemented yet."},
)

if len(CAPABILITY_DEFINITIONS) != 24:
    raise RuntimeError("console capability registry must contain exactly 24 entries")
if len({item["id"] for item in CAPABILITY_DEFINITIONS}) != 24:
    raise RuntimeError("console capability IDs must be unique")
if any(item["status"] not in VALID_STATUSES for item in CAPABILITY_DEFINITIONS):
    raise RuntimeError("console capability registry contains an invalid status")


def _count_nonempty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _snapshot_capability(item: dict[str, Any], snapshot) -> None:
    item["status"] = snapshot.status
    item["reason"] = snapshot.reason
    item["record_count"] = snapshot.record_count
    item["provenance_complete"] = snapshot.provenance_complete


def _time_range(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    values: list[str] = []
    for row in rows:
        for key in ("observed_at_utc", "first_seen_at_utc", "last_seen_at_utc", "created_at_utc"):
            value = row.get(key)
            if value:
                values.append(str(value))
    if not values:
        return None
    return {"from": min(values), "to": max(values)}


def build_capabilities(root: Path) -> dict[str, Any]:
    """Build capability status from bounded repositories without mutating artifacts."""

    registry = RepositoryRegistry(root)
    snapshots = {status["repository"]: registry.snapshot(status["repository"]) for status in registry.statuses()}
    airport_count = _count_nonempty_lines(root / "data" / "reference" / "pr_airports.jsonl")
    capabilities = [dict(item) for item in CAPABILITY_DEFINITIONS]

    repository_binding = {
        "aircraft_viewport_list": "aircraft_states",
        "playback_datetime": "aircraft_states",
        "playback_timeline": "track_points",
        "aircraft_labels": "aircraft_profiles",
        "airport_operations": "airport_operational_states",
        "airport_badges": "airport_operational_states",
    }
    for item in capabilities:
        capability_id = item["id"]
        if capability_id == "airport_detail":
            item["record_count"] = airport_count
            if airport_count == 0:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "Puerto Rico airport registry artifact is absent or empty."
            continue
        repository_name = repository_binding.get(capability_id)
        if repository_name:
            _snapshot_capability(item, snapshots[repository_name])

    airport_snapshot = snapshots["airport_operational_states"]
    weather_count = sum(1 for row in airport_snapshot.rows if row.get("weather"))
    disruption_count = sum(1 for row in airport_snapshot.rows if row.get("events") or row.get("disruption_codes"))
    for item in capabilities:
        if item["id"] == "airport_weather":
            item["record_count"] = weather_count
            if weather_count:
                item["status"] = airport_snapshot.status
                item["reason"] = "Airport-state records include weather payloads."
            else:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "No configured airport-state record includes weather data."
        elif item["id"] == "airport_disruptions":
            item["record_count"] = disruption_count
            if disruption_count:
                item["status"] = airport_snapshot.status
                item["reason"] = "Airport-state records include disruption or event payloads."
            else:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "No configured airport-state record includes disruption data."

    all_rows = [row for snapshot in snapshots.values() for row in snapshot.rows]
    synthetic_fixture = root / "exports" / "examples" / "synthetic_airspace_package" / "observations.csv"
    if synthetic_fixture.is_file():
        with synthetic_fixture.open("r", encoding="utf-8", newline="") as handle:
            for source in csv.DictReader(handle):
                source = dict(source)
                source["synthetic"] = str(source.get("synthetic") or "").lower() == "true"
                source["artifact_path"] = str(synthetic_fixture)
                source["ingest_adapter"] = "capabilities:synthetic_observation_fixture"
                provenance, _ = build_provenance(source)
                source_record_id = provenance["source_record_id"]
                if not any(row.get("provenance", {}).get("source_record_id") == source_record_id for row in all_rows):
                    all_rows.append({"synthetic": True, "provenance": provenance})
    source_methods = sorted(
        {
            str(row.get("provenance", {}).get("source_method"))
            for row in all_rows
            if row.get("provenance", {}).get("source_method")
        }
    )
    source_families = sorted(
        {
            str(row.get("provenance", {}).get("source_family"))
            for row in all_rows
            if row.get("provenance", {}).get("source_family")
        }
    )
    for item in capabilities:
        if item["id"] == "source_visibility":
            item["record_count"] = len(all_rows)
            item["provenance_complete"] = all(snapshot.provenance_complete for snapshot in snapshots.values())
            if not all_rows:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "No source-backed repository rows are available."
            elif all(bool(row.get("synthetic")) for row in all_rows):
                item["status"] = "available_synthetic_only"
                item["reason"] = "Only synthetic source rows are currently visible."
            elif any(snapshot.status == "degraded" for snapshot in snapshots.values()):
                item["status"] = "degraded"
                item["reason"] = "Source visibility is available with repository warnings or rejected rows."
            else:
                item["status"] = "available"
                item["reason"] = "Canonical source methods are populated from repository provenance."

    data_planes: dict[str, dict[str, Any]] = {}
    for family in ("operational_position", "screenshot_evidence", "official_record", "secondary_reference", "synthetic_test"):
        family_rows = [row for row in all_rows if row.get("provenance", {}).get("source_family") == family]
        data_planes[family] = {
            "available": bool(family_rows),
            "record_count": len(family_rows),
            "synthetic_only": bool(family_rows) and all(bool(row.get("synthetic")) for row in family_rows),
        }

    return {
        "api_version": API_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "mode": "diagnostic",
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "capability_count": len(capabilities),
        "coverage_percent": 100.0,
        "capabilities": capabilities,
        "repositories": registry.statuses(),
        "source_methods": source_methods,
        "source_families": source_families,
        "data_time_range": _time_range(all_rows),
        "data_planes": data_planes,
        "map_runtime": {
            "engine": "MapLibre GL JS",
            "route": "/console",
            "offline_basemap_id": "local-blank-diagnostic",
            "network_required_for_blank_diagnostic": False,
            "provider_keys_required": False,
            "attribution_always_visible": True,
            "webgl_cleanup_required": True,
        },
        "policy": {
            "fr24_scraping": False,
            "proprietary_asset_copying": False,
            "synthetic_production_eligible": False,
            "utc_required": True,
            "row_level_provenance_required": True,
            "bounded_artifact_discovery": True,
            "silent_empty_collections": False,
        },
    }
