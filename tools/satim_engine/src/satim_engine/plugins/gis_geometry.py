"""Pure, dependency-free geometry helpers for the SATIM GIS join.

Deliberately imports nothing beyond the standard library so the offline
geometric contract can be exercised without pandas/GDAL/GeoPandas. The pandas-
facing :func:`satim_engine.plugins.gis_join.bbox_context_join` builds on these.

A bounding box is ``(min_lon, min_lat, max_lon, max_lat)`` — GeoJSON bbox order.
Distances are planar degree approximations (no projection), adequate for coarse
"inside / how far outside" context ranking; a production backend should replace
:func:`bbox_distance_deg` with a projected/geodesic metric.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence, Tuple

BBox = Tuple[float, float, float, float]


def layer_bbox(layer: Any) -> Optional[BBox]:
    """Return a normalized bbox for *layer*, or ``None`` if it has no geometry.

    Recognized shapes (all pure data, no I/O):

    * a mapping with a 4-element ``"bbox"`` in GeoJSON order;
    * a mapping with ``"points"`` — an iterable of ``(lon, lat)`` pairs whose
      extent becomes the bbox;
    * a bare 4-element sequence treated directly as a bbox.

    Opaque objects and unrecognized mappings return ``None`` so callers can fall
    back to context-only enrichment without crashing.
    """
    if isinstance(layer, Mapping):
        bbox = layer.get("bbox")
        if _is_bbox_like(bbox):
            return _coerce_bbox(bbox)  # type: ignore[arg-type]
        points = layer.get("points")
        if points:
            return _bbox_from_points(points)
        return None
    if _is_bbox_like(layer):
        return _coerce_bbox(layer)  # type: ignore[arg-type]
    return None


def point_in_bbox(lat: float, lon: float, bbox: BBox) -> bool:
    """Exact membership test for a point inside (or on the edge of) *bbox*."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lon <= lon <= max_lon) and (min_lat <= lat <= max_lat)


def bbox_distance_deg(lat: float, lon: float, bbox: BBox) -> float:
    """Planar degree distance from a point to *bbox* (``0.0`` if inside)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    dx = max(min_lon - lon, 0.0, lon - max_lon)
    dy = max(min_lat - lat, 0.0, lat - max_lat)
    return math.hypot(dx, dy)


def resolve_geometry_layers(layers: Optional[Mapping[str, Any]]) -> list[tuple[str, BBox]]:
    """Return ``[(name, bbox), ...]`` for every layer with usable geometry."""
    if not layers:
        return []
    resolved: list[tuple[str, BBox]] = []
    for name, layer in layers.items():
        bbox = layer_bbox(layer)
        if bbox is not None:
            resolved.append((str(name), bbox))
    return resolved


def as_float(value: Any) -> Optional[float]:
    """Coerce *value* to a finite float, or ``None`` if it isn't numeric."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _is_bbox_like(value: Any) -> bool:
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        return False
    if not isinstance(value, Sequence):
        return False
    if len(value) != 4:
        return False
    return all(as_float(v) is not None for v in value)


def _coerce_bbox(value: Sequence[Any]) -> BBox:
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in value)
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat
    return (min_lon, min_lat, max_lon, max_lat)


def _bbox_from_points(points: Any) -> Optional[BBox]:
    lons: list[float] = []
    lats: list[float] = []
    for pair in points:
        if not isinstance(pair, Sequence) or len(pair) < 2:
            continue
        flon, flat = as_float(pair[0]), as_float(pair[1])
        if flon is None or flat is None:
            continue
        lons.append(flon)
        lats.append(flat)
    if not lons:
        return None
    return (min(lons), min(lats), max(lons), max(lats))
