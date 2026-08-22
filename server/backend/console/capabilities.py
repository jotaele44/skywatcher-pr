"""24-of-24 capability registry for the diagnostic console."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .source_taxonomy import SOURCE_TAXONOMY_VERSION, build_provenance

API_VERSION = "0.1.0"
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
    {"id": "view_modes", "label": "Map/list/airport/fleet view modes", "phase": 4, "status": "degraded", "reason": "Separate pages and aircraft card/table views exist, but no synchronized console."},
    {"id": "aircraft_viewport_list", "label": "Viewport aircraft list", "phase": 4, "status": "unavailable_no_artifact", "reason": "No normalized aircraft-state collection is connected."},
    {"id": "configurable_columns", "label": "Configurable columns", "phase": 4, "status": "unavailable_no_adapter", "reason": "Column registry is not implemented yet."},
    {"id": "map_navigation", "label": "Interactive map navigation", "phase": 3, "status": "unavailable_no_adapter", "reason": "The React surface currently uses a diagnostic SVG shell."},
    {"id": "geolocation", "label": "Geolocation", "phase": 3, "status": "unavailable_no_adapter", "reason": "Browser geolocation control is not implemented yet."},
    {"id": "playback_datetime", "label": "Playback date/time selection", "phase": 5, "status": "available_synthetic_only", "reason": "Synthetic observations include exact timestamps; no operational history is connected."},
    {"id": "playback_timeline", "label": "Playback timeline", "phase": 5, "status": "unavailable_no_artifact", "reason": "No normalized time-indexed aircraft-state store is connected."},
    {"id": "widgets", "label": "Console widgets", "phase": 6, "status": "degraded", "reason": "Diagnostic dashboard panels exist but are not dockable console widgets."},
    {"id": "basemap_controls", "label": "Basemap controls", "phase": 3, "status": "unavailable_no_adapter", "reason": "Interactive map runtime and basemap registry are not implemented yet."},
    {"id": "map_brightness", "label": "Map brightness", "phase": 3, "status": "unavailable_no_adapter", "reason": "Interactive map style controls are not implemented yet."},
    {"id": "day_night_overlay", "label": "Day/night overlay", "phase": 6, "status": "unavailable_no_adapter", "reason": "Solar terminator layer is not implemented yet."},
    {"id": "atc_overlays", "label": "ATC overlays", "phase": 6, "status": "unavailable_no_artifact", "reason": "Authoritative display-ready ATC boundary layers are not connected."},
    {"id": "oceanic_tracks", "label": "Oceanic tracks", "phase": 6, "status": "unavailable_no_adapter", "reason": "No official or licensed oceanic-track adapter is configured."},
    {"id": "airport_badges", "label": "Airport badges", "phase": 6, "status": "degraded", "reason": "Airport markers exist, but operational status badges do not."},
    {"id": "aircraft_labels", "label": "Aircraft labels", "phase": 6, "status": "unavailable_no_artifact", "reason": "Aircraft profile and live-state collections are not connected."},
    {"id": "aircraft_styling", "label": "Aircraft styling", "phase": 6, "status": "unavailable_no_adapter", "reason": "Interactive aircraft symbol renderer is not implemented yet."},
    {"id": "source_visibility", "label": "Source visibility", "phase": 1, "status": "degraded", "reason": "Canonical source taxonomy is available; operational source collections are not connected."},
    {"id": "unit_preferences", "label": "Unit preferences", "phase": 4, "status": "unavailable_no_adapter", "reason": "Unit provider and preference repository are not implemented yet."},
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


def _read_observations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _time_range(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    parsed: list[datetime] = []
    for row in rows:
        text = str(row.get("event_datetime") or row.get("observed_at") or "").strip()
        if not text:
            continue
        try:
            parsed.append(datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc))
        except ValueError:
            continue
    if not parsed:
        return None
    return {
        "from": min(parsed).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "to": max(parsed).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_capabilities(root: Path) -> dict[str, Any]:
    """Build capability status from repository artifacts without mutating them."""

    airport_path = root / "data" / "reference" / "pr_airports.jsonl"
    observation_path = root / "exports" / "examples" / "synthetic_airspace_package" / "observations.csv"
    observations = _read_observations(observation_path)
    airport_count = _count_nonempty_lines(airport_path)

    source_methods: set[str] = set()
    source_families: set[str] = set()
    for row in observations:
        row["synthetic"] = str(row.get("synthetic", "")).lower() == "true"
        provenance, _ = build_provenance(row)
        source_methods.add(str(provenance["source_method"]))
        source_families.add(str(provenance["source_family"]))

    capabilities = [dict(item) for item in CAPABILITY_DEFINITIONS]
    for item in capabilities:
        if item["id"] == "airport_detail":
            item["record_count"] = airport_count
            if airport_count == 0:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "Puerto Rico airport registry artifact is absent or empty."
        elif item["id"] in {"playback_datetime", "source_visibility"}:
            item["record_count"] = len(observations)
            if not observations:
                item["status"] = "unavailable_no_artifact"
                item["reason"] = "Synthetic observation fixture is absent or empty."

    return {
        "api_version": API_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "mode": "diagnostic",
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "capability_count": len(capabilities),
        "coverage_percent": 100.0,
        "capabilities": capabilities,
        "source_methods": sorted(source_methods),
        "source_families": sorted(source_families),
        "data_time_range": _time_range(observations),
        "data_planes": {
            "operational_position": {
                "available": False,
                "record_count": 0,
                "reason": "No owned or licensed operational aircraft-state repository is connected.",
            },
            "screenshot_evidence": {
                "available": (root / "fr24").exists(),
                "reason": "FR24 screenshots are evidence inputs only; no proprietary endpoint access is performed.",
            },
            "synthetic_test": {
                "available": bool(observations),
                "record_count": len(observations),
            },
        },
        "policy": {
            "fr24_scraping": False,
            "proprietary_asset_copying": False,
            "synthetic_production_eligible": False,
            "utc_required": True,
            "row_level_provenance_required": True,
        },
    }
