"""Flight-endpoint matching against the airport registry (strategy #3).

Implements the schema'd-but-unbuilt flight_endpoint_event: matches a fused
wave's first/last observed positions against configs/airport_registry.yaml by
haversine distance and emits schema-conformant endpoint events
(schemas/flight_endpoint_event.schema.json).

Contract discipline (docs/FR24_NON_SYNTHETIC_EXPORT_PLAN.md check #3): every
match exposes match_method, distance_m, matched_facility_id, confidence, and
review_status. Matches are candidate signals — review_status='needs_review',
never auto-promoted; endpoint_type describes the *track* endpoint (first/last
frame), not a confirmed takeoff or landing.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from pipeline.normalize_locations import load_simple_yaml

REPO = Path(__file__).resolve().parents[1]
AIRPORT_REGISTRY_YAML = REPO / "configs" / "airport_registry.yaml"

EARTH_RADIUS_M = 6_371_000.0

# Distance banding: a track endpoint within 3 km of a facility is a solid
# candidate match; 3-10 km is a weak one; beyond 10 km is no match.
NEAR_THRESHOLD_M = 3_000.0
FAR_THRESHOLD_M = 10_000.0
NEAR_CONFIDENCE = 0.7
FAR_CONFIDENCE = 0.4

MATCH_METHOD = "track_endpoint_distance"
REVIEW_STATUS = "needs_review"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (stdlib only)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def load_airports(path: Optional[Path] = None) -> List[dict]:
    """Airport rows from configs/airport_registry.yaml (dependency-free loader)."""
    data = load_simple_yaml(path or AIRPORT_REGISTRY_YAML)
    airports = []
    for entry in data.get("airports", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("lat") is None or entry.get("lon") is None:
            continue
        airports.append(entry)
    return airports


def facility_code(airport: dict) -> str:
    """Preferred short code for adapter origin/destination fields."""
    return str(airport.get("iata") or airport.get("icao") or airport.get("airport_id") or "")


def nearest_airport(lat: float, lon: float,
                    airports: List[dict]) -> Optional[Tuple[dict, float]]:
    """(airport, distance_m) of the closest registry facility, or None."""
    best: Optional[Tuple[dict, float]] = None
    for airport in airports:
        distance = haversine_m(lat, lon, float(airport["lat"]), float(airport["lon"]))
        if best is None or distance < best[1]:
            best = (airport, distance)
    return best


def match_endpoint(lat: float, lon: float,
                   airports: List[dict]) -> Optional[Tuple[dict, float, float]]:
    """(airport, distance_m, confidence) within the 10 km band, else None."""
    best = nearest_airport(lat, lon, airports)
    if best is None:
        return None
    airport, distance = best
    if distance <= NEAR_THRESHOLD_M:
        return airport, distance, NEAR_CONFIDENCE
    if distance <= FAR_THRESHOLD_M:
        return airport, distance, FAR_CONFIDENCE
    return None


def endpoint_events_for_wave(fused: dict, airports: List[dict], *,
                             observation_id: str, source_id: str,
                             lineage_id: str, synthetic: bool) -> List[dict]:
    """Schema-conformant flight_endpoint_event dicts for a fused wave.

    Matches the first point ('start') and last point ('end') that carry both
    coordinates and a timestamp; a single-frame wave yields at most one
    'overflight_near_facility' event. Points without coordinates or without a
    timestamp are skipped (event_datetime is schema-required — never invented).
    """
    points = [
        p for p in fused.get("points", [])
        if p.get("lat") is not None and p.get("lon") is not None
        and p.get("timestamp_iso")
    ]
    if not points:
        return []

    if len(points) == 1:
        candidates = [(points[0], "overflight_near_facility")]
    else:
        candidates = [(points[0], "start"), (points[-1], "end")]

    events: List[dict] = []
    for point, endpoint_type in candidates:
        match = match_endpoint(float(point["lat"]), float(point["lon"]), airports)
        if match is None:
            continue
        airport, distance, confidence = match
        events.append({
            "endpoint_event_id": f"ep-{observation_id}-{endpoint_type}",
            "observation_id": observation_id,
            "event_datetime": point["timestamp_iso"],
            "endpoint_type": endpoint_type,
            "aircraft_registration": fused.get("registration") or None,
            "callsign": fused.get("callsign") or None,
            "matched_facility_id": str(airport["airport_id"]),
            "matched_zone_id": None,
            "match_method": MATCH_METHOD,
            "distance_m": round(distance, 1),
            "bearing": None,
            "confidence": confidence,
            "source_id": source_id,
            "lineage_id": lineage_id,
            "synthetic": bool(synthetic),
            "review_status": REVIEW_STATUS,
            "notes": (
                f"nearest registry facility {facility_code(airport)}"
                f" at {distance:.0f} m (bands: <={NEAR_THRESHOLD_M:.0f} m ->"
                f" {NEAR_CONFIDENCE}, <={FAR_THRESHOLD_M:.0f} m -> {FAR_CONFIDENCE})"
            ),
            # Convenience for to_adapter_row (not part of the schema; strip
            # with schema_fields() before schema validation/export).
            "matched_facility_code": facility_code(airport),
        })
    return events


def schema_fields(event: dict) -> dict:
    """The event without convenience extras — exactly the schema's properties."""
    return {k: v for k, v in event.items() if k != "matched_facility_code"}
