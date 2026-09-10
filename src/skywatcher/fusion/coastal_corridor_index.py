"""Aggregate corridor attachment helpers for Puerto Rico analytical review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import asin, cos, isfinite, radians, sin, sqrt

DEFAULT_CORRIDORS: tuple[dict[str, object], ...] = (
    {"corridor_id": "sj_corridor", "name": "San Juan regional corridor", "domain": "air_maritime", "center_lat": 18.456, "center_lon": -66.098, "radius_km": 25.0},
    {"corridor_id": "ceiba_vieques_corridor", "name": "Eastern Puerto Rico corridor", "domain": "air_maritime", "center_lat": 18.235, "center_lon": -65.620, "radius_km": 30.0},
    {"corridor_id": "ponce_corridor", "name": "South coast regional corridor", "domain": "air_maritime", "center_lat": 18.010, "center_lon": -66.615, "radius_km": 25.0},
    {"corridor_id": "mona_corridor", "name": "Mona Passage regional corridor", "domain": "air_maritime", "center_lat": 18.200, "center_lon": -67.950, "radius_km": 55.0},
)


def finite_number(value: object, field: str) -> float:
    """Parse JSON numeric fields without admitting booleans, nulls or NaN."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = (
        finite_number(value, name)
        for value, name in zip((lat1, lon1, lat2, lon2), ("lat1", "lon1", "lat2", "lon2"), strict=True)
    )
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Coordinates must be within WGS84 latitude/longitude bounds")
    radius_km = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    # Antipodal rounding can put a a few ulps above one.
    return 2 * radius_km * asin(sqrt(min(1.0, max(0.0, a))))


def attach_corridor(event: Mapping[str, object], corridors: Sequence[Mapping[str, object]] = DEFAULT_CORRIDORS) -> dict[str, object]:
    """Attach an aggregate discovery candidate, never a canonical identity."""
    lat = finite_number(event.get("lat"), "lat")
    lon = finite_number(event.get("lon"), "lon")
    haversine_km(lat, lon, lat, lon)
    candidates = []
    distances = []
    for corridor in corridors:
        radius = finite_number(corridor.get("radius_km"), "radius_km")
        if radius < 0:
            raise ValueError("radius_km must be nonnegative")
        distance = haversine_km(lat, lon, finite_number(corridor.get("center_lat"), "center_lat"), finite_number(corridor.get("center_lon"), "center_lon"))
        distances.append(distance)
        if distance <= radius:
            candidates.append((distance, corridor))
    best_distance = min((distance for distance, _ in candidates), default=None)
    tied = [corridor for distance, corridor in candidates if distance == best_distance]
    enriched = dict(event)
    enriched.update({
        "corridor_id": None,
        "corridor_name": None,
        "corridor_distance_km": round(min(distances), 3) if distances else None,
        "corridor_candidates": [dict(corridor) for _, corridor in candidates],
        "corridor_status": "UNRESOLVED" if len(tied) > 1 else "OUTSIDE",
        "identity_effect": "NONE",
    })
    if len(tied) == 1 and best_distance is not None:
        best = tied[0]
        enriched.update({
            "corridor_id": best["corridor_id"],
            "corridor_name": best["name"],
            "corridor_distance_km": round(best_distance, 3),
            "corridor_status": "CANDIDATE_NOT_IDENTITY",
        })
    return enriched
