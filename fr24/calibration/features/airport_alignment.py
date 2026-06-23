"""Airport footprint alignment scoring for SATIM infrastructure features.

This module bridges the Puerto Rico airspace footprint registry into the SATIM
synthetic-boundary feature engine. It computes an ``airport_alignment`` score
that can be passed into ``compute_infrastructure_features`` and then weighted by
L5 classification. It never hard-rejects a candidate.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping

from .boundary_geometry import as_float, clamp01

DEFAULT_FOOTPRINT_REGISTRY_PATHS = (
    Path("registry/puerto_rico_airspace_footprints.csv"),
    Path("registry/puerto_rico_helipads.csv"),
)


@dataclass(frozen=True)
class AirportFootprint:
    footprint_id: str
    facility_name: str
    facility_type: str
    latitude: float
    longitude: float
    radius_m: float
    geometry_confidence: str = "low"


@dataclass(frozen=True)
class AirportAlignmentResult:
    airport_alignment: float
    nearest_footprint_id: str
    nearest_facility_name: str
    nearest_facility_type: str
    distance_m: float
    radius_m: float
    match_count: int


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2.0) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2.0) ** 2
    return 2.0 * earth_radius_m * asin(sqrt(a))


def footprint_from_row(row: Mapping[str, Any]) -> AirportFootprint | None:
    latitude = row.get("latitude")
    longitude = row.get("longitude")
    if latitude in (None, "") or longitude in (None, ""):
        return None

    radius = as_float(row.get("radius_m"), 250.0)
    if radius <= 0:
        radius = 250.0

    return AirportFootprint(
        footprint_id=str(row.get("footprint_id") or row.get("id") or "unknown"),
        facility_name=str(row.get("facility_name") or row.get("name") or "unknown"),
        facility_type=str(row.get("facility_type") or "airport_footprint"),
        latitude=float(latitude),
        longitude=float(longitude),
        radius_m=radius,
        geometry_confidence=str(row.get("geometry_confidence") or "low"),
    )


def load_airport_footprints(paths: Iterable[str | Path] = DEFAULT_FOOTPRINT_REGISTRY_PATHS) -> list[AirportFootprint]:
    footprints: list[AirportFootprint] = []
    for path_value in paths:
        path = Path(path_value)
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                footprint = footprint_from_row(row)
                if footprint is not None:
                    footprints.append(footprint)
    return footprints


def candidate_lat_lon(row: Mapping[str, Any]) -> tuple[float, float] | None:
    lat_value = row.get("candidate_latitude", row.get("latitude", row.get("lat")))
    lon_value = row.get("candidate_longitude", row.get("longitude", row.get("lon")))
    if lat_value in (None, "") or lon_value in (None, ""):
        return None
    return float(lat_value), float(lon_value)


def score_distance_to_footprint(distance_m: float, radius_m: float, angle_similarity: float = 1.0) -> float:
    """Score footprint alignment from distance and optional angle similarity.

    Distance inside the footprint radius scores high. The score decays to zero at
    twice the radius to catch near-edge apron/hangar candidates without turning
    the score into a hard rejection.
    """
    if radius_m <= 0:
        return 0.0
    distance_component = clamp01(1.0 - (distance_m / (radius_m * 2.0)))
    return clamp01(0.75 * distance_component + 0.25 * clamp01(angle_similarity))


def compute_airport_alignment(
    row: Mapping[str, Any],
    footprints: Iterable[AirportFootprint],
) -> AirportAlignmentResult:
    coords = candidate_lat_lon(row)
    if coords is None:
        return AirportAlignmentResult(0.0, "", "", "", 0.0, 0.0, 0)

    latitude, longitude = coords
    angle_similarity = clamp01(as_float(row.get("airport_angle_similarity"), 1.0))

    best_score = 0.0
    best_distance = 0.0
    best: AirportFootprint | None = None
    match_count = 0

    for footprint in footprints:
        distance = haversine_m(latitude, longitude, footprint.latitude, footprint.longitude)
        score = score_distance_to_footprint(distance, footprint.radius_m, angle_similarity)
        if score > 0.0:
            match_count += 1
        if score > best_score:
            best_score = score
            best_distance = distance
            best = footprint

    if best is None:
        return AirportAlignmentResult(0.0, "", "", "", 0.0, 0.0, 0)

    return AirportAlignmentResult(
        airport_alignment=round(best_score, 4),
        nearest_footprint_id=best.footprint_id,
        nearest_facility_name=best.facility_name,
        nearest_facility_type=best.facility_type,
        distance_m=round(best_distance, 2),
        radius_m=best.radius_m,
        match_count=match_count,
    )


def enrich_candidate_with_airport_alignment(
    row: Mapping[str, Any],
    footprints: Iterable[AirportFootprint],
) -> dict[str, Any]:
    result = compute_airport_alignment(row, footprints)
    enriched = dict(row)
    enriched["airport_alignment"] = str(result.airport_alignment)
    enriched["nearest_airport_footprint_id"] = result.nearest_footprint_id
    enriched["nearest_airport_facility_name"] = result.nearest_facility_name
    enriched["nearest_airport_facility_type"] = result.nearest_facility_type
    enriched["nearest_airport_footprint_distance_m"] = str(result.distance_m)
    enriched["airport_footprint_match_count"] = str(result.match_count)
    return enriched
