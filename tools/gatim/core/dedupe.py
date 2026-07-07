"""Coordinate clustering helpers for GATIM rows."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    value = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_M * asin(sqrt(value))


def assign_clusters(rows: list, radius_m: float = 5.0) -> list:
    clusters: list[list[int]] = []
    centroids: list[tuple[float, float]] = []
    for idx, row in enumerate(rows):
        try:
            lat = float(row.lat)
            lon = float(row.lon)
        except (TypeError, ValueError):
            row.dedupe_cluster_id = "NO_COORD"
            row.dedupe_cluster_size = ""
            continue
        match_idx = None
        for centroid_idx, centroid in enumerate(centroids):
            if haversine_m(lat, lon, centroid[0], centroid[1]) <= radius_m:
                match_idx = centroid_idx
                break
        if match_idx is None:
            clusters.append([idx])
            centroids.append((lat, lon))
        else:
            clusters[match_idx].append(idx)
            size = len(clusters[match_idx])
            old_lat, old_lon = centroids[match_idx]
            centroids[match_idx] = ((old_lat * (size - 1) + lat) / size, (old_lon * (size - 1) + lon) / size)
    for cluster_idx, members in enumerate(clusters, start=1):
        for member_idx in members:
            rows[member_idx].dedupe_cluster_id = f"GCL_{cluster_idx:05d}"
            rows[member_idx].dedupe_cluster_size = str(len(members))
    return rows
