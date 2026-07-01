"""Aggregate corridor attachment helpers for Puerto Rico analytical review."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Mapping, Sequence

DEFAULT_CORRIDORS: tuple[dict[str, object], ...] = (
    {"corridor_id": "sj_corridor", "name": "San Juan regional corridor", "domain": "air_maritime", "center_lat": 18.456, "center_lon": -66.098, "radius_km": 25.0},
    {"corridor_id": "ceiba_vieques_corridor", "name": "Eastern Puerto Rico corridor", "domain": "air_maritime", "center_lat": 18.235, "center_lon": -65.620, "radius_km": 30.0},
    {"corridor_id": "ponce_corridor", "name": "South coast regional corridor", "domain": "air_maritime", "center_lat": 18.010, "center_lon": -66.615, "radius_km": 25.0},
    {"corridor_id": "mona_corridor", "name": "Mona Passage regional corridor", "domain": "air_maritime", "center_lat": 18.200, "center_lon": -67.950, "radius_km": 55.0},
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def attach_corridor(event: Mapping[str, object], corridors: Sequence[Mapping[str, object]] = DEFAULT_CORRIDORS) -> dict[str, object]:
    """Attach nearest aggregate corridor to an event-like record."""

    lat = float(event.get("lat", 0.0))
    lon = float(event.get("lon", 0.0))
    best = None
    best_distance = float("inf")
    for corridor in corridors:
        distance = haversine_km(lat, lon, float(corridor["center_lat"]), float(corridor["center_lon"]))
        if distance < best_distance:
            best = corridor
            best_distance = distance

    enriched = dict(event)
    if best and best_distance <= float(best["radius_km"]):
        enriched["corridor_id"] = best["corridor_id"]
        enriched["corridor_name"] = best["name"]
        enriched["corridor_distance_km"] = round(best_distance, 3)
    else:
        enriched["corridor_id"] = None
        enriched["corridor_name"] = None
        enriched["corridor_distance_km"] = round(best_distance, 3)
    return enriched
