"""Flight-endpoint matching against the airport registry (strategy #3).

Implements the schema'd-but-unbuilt flight_endpoint_event: matches a fused
wave's first/last observed positions against configs/airport_registry.yaml by
haversine distance and emits schema-conformant endpoint events
(schemas/flight_endpoint_event.schema.json).

Contract discipline: distance matches are discovery candidates only. They expose
match_method, distance_m, matched_facility_id, confidence, review_status,
identity_state, and association_state. The matched facility field is a candidate
reference, not airport identity or a takeoff/landing claim. Route promotion must
be explicit downstream.
"""
from __future__ import annotations

import math
from pathlib import Path

from pipeline.normalize_locations import load_simple_yaml

REPO = Path(__file__).resolve().parents[1]
AIRPORT_REGISTRY_YAML = REPO / "configs" / "airport_registry.yaml"

EARTH_RADIUS_M = 6_371_000.0
NEAR_THRESHOLD_M = 3_000.0
FAR_THRESHOLD_M = 10_000.0
NEAR_CONFIDENCE = 0.7
FAR_CONFIDENCE = 0.4

MATCH_METHOD = "track_endpoint_distance"
REVIEW_STATUS = "needs_review"
IDENTITY_STATE = "CANDIDATE_NOT_IDENTITY"
ASSOCIATION_STATE = "DISCOVERY_ONLY"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (stdlib only)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def load_airports(path: Path | None = None) -> list[dict]:
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


def nearest_airport(
    lat: float, lon: float, airports: list[dict]
) -> tuple[dict, float] | None:
    """(airport, distance_m) of the closest registry facility, or None."""
    best: tuple[dict, float] | None = None
    for airport in airports:
        distance = haversine_m(lat, lon, float(airport["lat"]), float(airport["lon"]))
        if best is None or distance < best[1]:
            best = (airport, distance)
    return best


def match_endpoint(
    lat: float, lon: float, airports: list[dict]
) -> tuple[dict, float, float] | None:
    """Return a distance-band candidate; never an identity or landing binding."""
    best = nearest_airport(lat, lon, airports)
    if best is None:
        return None
    airport, distance = best
    if distance <= NEAR_THRESHOLD_M:
        return airport, distance, NEAR_CONFIDENCE
    if distance <= FAR_THRESHOLD_M:
        return airport, distance, FAR_CONFIDENCE
    return None


def endpoint_events_for_wave(
    fused: dict,
    airports: list[dict],
    *,
    observation_id: str,
    source_id: str,
    lineage_id: str,
    synthetic: bool,
) -> list[dict]:
    """Schema-conformant candidate endpoint events for a fused wave.

    ``endpoint_type`` describes the observed track endpoint only. The emitted
    ``matched_facility_id`` is the nearest registry candidate within the band;
    identity_state and association_state block its use as route truth.
    """
    points = [
        p
        for p in fused.get("points", [])
        if p.get("lat") is not None
        and p.get("lon") is not None
        and p.get("timestamp_iso")
    ]
    if not points:
        return []

    if len(points) == 1:
        candidates = [(points[0], "overflight_near_facility")]
    else:
        candidates = [(points[0], "start"), (points[-1], "end")]

    events: list[dict] = []
    for point, endpoint_type in candidates:
        match = match_endpoint(float(point["lat"]), float(point["lon"]), airports)
        if match is None:
            continue
        airport, distance, confidence = match
        events.append(
            {
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
                "identity_state": IDENTITY_STATE,
                "association_state": ASSOCIATION_STATE,
                "notes": (
                    f"nearest registry facility {facility_code(airport)}"
                    f" at {distance:.0f} m; discovery only, not identity/landing"
                ),
                "matched_facility_code": facility_code(airport),
            }
        )
    return events


def schema_fields(event: dict) -> dict:
    """Return the event without adapter-only convenience fields."""
    return {k: v for k, v in event.items() if k != "matched_facility_code"}
