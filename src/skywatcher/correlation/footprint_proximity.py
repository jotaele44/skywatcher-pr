"""Correlate aircraft events against static airspace footprints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from skywatcher.core.geo_utils import EARTH_RADIUS_M, haversine_m  # noqa: F401
from skywatcher.registry.airspace_footprints import AirspaceFootprint


@dataclass(frozen=True)
class FootprintMatch:
    footprint_id: str
    facility_name: str
    facility_type: str
    operator_class: str
    distance_m: float
    radius_m: int
    match_type: str
    score: float
    explanation: str


def score_match(distance_m: float, radius_m: int, facility_type: str) -> float:
    if radius_m <= 0:
        return 0.0
    proximity = max(0.0, 1.0 - (distance_m / radius_m))
    boost = {
        "helipad": 0.15,
        "military_unit": 0.20,
        "law_enforcement_air": 0.20,
        "government_aviation": 0.15,
        "cargo_facility": 0.05,
        "mro": 0.10,
    }.get(facility_type, 0.0)
    return min(1.0, round(proximity + boost, 3))


def correlate_point_to_footprints(
    latitude: float,
    longitude: float,
    footprints: Iterable[AirspaceFootprint],
    max_distance_m: float | None = None,
) -> list[FootprintMatch]:
    matches: list[FootprintMatch] = []
    for footprint in footprints:
        if footprint.latitude is None or footprint.longitude is None:
            continue
        radius = max_distance_m if max_distance_m is not None else footprint.radius_m
        distance = haversine_m(latitude, longitude, footprint.latitude, footprint.longitude)
        if distance <= radius:
            score = score_match(distance, footprint.radius_m, footprint.facility_type)
            matches.append(
                FootprintMatch(
                    footprint_id=footprint.footprint_id,
                    facility_name=footprint.facility_name,
                    facility_type=footprint.facility_type,
                    operator_class=footprint.operator_class,
                    distance_m=round(distance, 1),
                    radius_m=footprint.radius_m,
                    match_type="near_ground_aviation_node",
                    score=score,
                    explanation=(
                        f"Point is {round(distance, 1)} m from {footprint.facility_name} "
                        f"({footprint.facility_type})."
                    ),
                )
            )
    return sorted(matches, key=lambda item: (item.distance_m, -item.score))


def matches_as_dicts(matches: Iterable[FootprintMatch]) -> list[dict[str, object]]:
    return [asdict(match) for match in matches]
