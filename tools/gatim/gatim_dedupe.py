"""Coordinate dedupe for GATIM candidate rows."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    value = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_M * asin(sqrt(value))


def assign_clusters(rows: list, radius_m: float = 5.0) -> list:
    clusters: list[list[int]] = []
    centroids: list[tuple[float, float]] = []
    for idx, row in enumerate(rows):
        try:
            lat, lon = float(row.lat), float(row.lon)
        except (TypeError, ValueError):
            row.dedupe_cluster_id = "NO_COORD"
            row.dedupe_cluster_size = ""
            continue
        match = None
        for cid, (clat, clon) in enumerate(centroids, start=1):
            if haversine_m(lat, lon, clat, clon) <= radius_m:
                match = cid - 1
                break
        if match is None:
            clusters.append([idx])
            centroids.append((lat, lon))
        else:
            clusters[match].append(idx)
            size = len(clusters[match])
            old_lat, old_lon = centroids[match]
            centroids[match] = ((old_lat * (size - 1) + lat) / size, (old_lon * (size - 1) + lon) / size)
    for cid, members in enumerate(clusters, start=1):
        cluster_id = f"GCL_{cid:05d}"
        size = str(len(members))
        for member_idx in members:
            rows[member_idx].dedupe_cluster_id = cluster_id
            rows[member_idx].dedupe_cluster_size = size
    return rows
