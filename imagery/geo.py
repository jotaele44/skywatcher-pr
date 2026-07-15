"""
Imagery — geometry helpers.

Self-contained lat/lon → bbox and slippy-tile math (mirrors
``earthgpt/tile_utils.py`` so the package stays identical across repos and has
no cross-package import), plus a Puerto Rico AOI overlap check that matches the
satellite_source_manifest schema envelope.
"""

from __future__ import annotations

import math

from . import config


def bbox_from_point(
    lat: float, lon: float, buffer_deg: float | None = None
) -> list[float]:
    """Build an EPSG:4326 bbox (west, south, east, north) around a point.

    ``buffer_deg`` is the half-width in degrees; defaults to
    ``config.DEFAULT_BUFFER_DEG``. Latitude is clamped to [-90, 90].
    """
    b = config.DEFAULT_BUFFER_DEG if buffer_deg is None else buffer_deg
    west = lon - b
    east = lon + b
    south = max(-90.0, lat - b)
    north = min(90.0, lat + b)
    return [west, south, east, north]


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 lat/lon to XYZ tile (x, y) at ``zoom`` (Web Mercator)."""
    lat_r = math.radians(lat)
    n = 2.0**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    """Return the (lat, lon) center of a (west, south, east, north) bbox."""
    west, south, east, north = bbox[:4]
    return (south + north) / 2.0, (west + east) / 2.0


def overlaps_pr(bbox: list[float]) -> bool:
    """True if ``bbox`` overlaps the Puerto Rico AOI envelope.

    Mirrors readiness/satellite_ingest.py::_check_bbox_overlap so imagery
    footprints agree with what the manifest pipeline will accept.
    """
    if not bbox or len(bbox) < 4:
        return False
    west, south, east, north = bbox[:4]
    if (
        east < config.PR_LON_MIN
        or west > config.PR_LON_MAX
        or north < config.PR_LAT_MIN
        or south > config.PR_LAT_MAX
    ):
        return False
    return True


def clamp_bbox_to_pr(bbox: list[float]) -> list[float]:
    """Clamp a bbox to the PR envelope so downstream ingest accepts it.

    The satellite_source_manifest schema constrains coordinates to the PR
    envelope; clamp fetched footprints to keep manifests valid even when the
    requested buffer spills slightly past the island.
    """
    west, south, east, north = bbox[:4]
    return [
        min(max(west, config.PR_LON_MIN), config.PR_LON_MAX),
        min(max(south, config.PR_LAT_MIN), config.PR_LAT_MAX),
        min(max(east, config.PR_LON_MIN), config.PR_LON_MAX),
        min(max(north, config.PR_LAT_MIN), config.PR_LAT_MAX),
    ]
