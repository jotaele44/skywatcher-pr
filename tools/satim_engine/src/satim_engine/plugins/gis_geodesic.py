"""WGS84 geodesic primitives for SATIM GIS joins."""
from __future__ import annotations

import math

A = 6378137.0
F = 1 / 298.257223563
B = (1 - F) * A


def _valid(lon: float, lat: float) -> tuple[float, float]:
    lon = float(lon)
    lat = float(lat)
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise ValueError("invalid WGS84 coordinate")
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("invalid WGS84 coordinate")
    return lon, lat


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = map(math.radians, (lat1, lat2))
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Vincenty inverse distance with bounded spherical fallback."""
    lon1, lat1 = _valid(lon1, lat1)
    lon2, lat2 = _valid(lon2, lat2)
    if (lon1, lat1) == (lon2, lat2):
        return 0.0

    p1, p2 = map(math.radians, (lat1, lat2))
    u1 = math.atan((1 - F) * math.tan(p1))
    u2 = math.atan((1 - F) * math.tan(p2))
    longitude_delta = math.radians(lon2 - lon1)
    lam = longitude_delta

    for _ in range(200):
        sin_lam = math.sin(lam)
        cos_lam = math.cos(lam)
        sin_sigma = math.sqrt(
            (math.cos(u2) * sin_lam) ** 2
            + (math.cos(u1) * math.sin(u2) - math.sin(u1) * math.cos(u2) * cos_lam) ** 2
        )
        if sin_sigma == 0:
            return 0.0
        cos_sigma = math.sin(u1) * math.sin(u2) + math.cos(u1) * math.cos(u2) * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = math.cos(u1) * math.cos(u2) * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha**2
        cos_2sigma_m = (
            0.0
            if cos_sq_alpha == 0
            else cos_sigma - 2 * math.sin(u1) * math.sin(u2) / cos_sq_alpha
        )
        c = F / 16 * cos_sq_alpha * (4 + F * (4 - 3 * cos_sq_alpha))
        next_lam = longitude_delta + (1 - c) * F * sin_alpha * (
            sigma
            + c
            * sin_sigma
            * (cos_2sigma_m + c * cos_sigma * (-1 + 2 * cos_2sigma_m**2))
        )
        if abs(next_lam - lam) < 1e-12:
            lam = next_lam
            break
        lam = next_lam
    else:
        return _haversine(lon1, lat1, lon2, lat2)

    reduced = cos_sq_alpha * (A**2 - B**2) / B**2
    coef_a = 1 + reduced / 16384 * (4096 + reduced * (-768 + reduced * (320 - 175 * reduced)))
    coef_b = reduced / 1024 * (256 + reduced * (-128 + reduced * (74 - 47 * reduced)))
    delta_sigma = coef_b * sin_sigma * (
        cos_2sigma_m
        + coef_b
        / 4
        * (
            cos_sigma * (-1 + 2 * cos_2sigma_m**2)
            - coef_b
            / 6
            * cos_2sigma_m
            * (-3 + 4 * sin_sigma**2)
            * (-3 + 4 * cos_2sigma_m**2)
        )
    )
    return B * coef_a * (sigma - delta_sigma)


def bbox_distance_m(lat: float, lon: float, bbox) -> float:
    lon, lat = _valid(lon, lat)
    if len(bbox) != 4:
        raise ValueError("bbox must contain four coordinates")
    min_lon, min_lat, max_lon, max_lat = map(float, bbox)
    _valid(min_lon, min_lat)
    _valid(max_lon, max_lat)
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("invalid bbox ordering")
    if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
        return 0.0
    qlon = min(max(lon, min_lon), max_lon)
    qlat = min(max(lat, min_lat), max_lat)
    return distance_m(lon, lat, qlon, qlat)
