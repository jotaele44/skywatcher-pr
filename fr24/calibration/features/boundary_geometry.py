"""L0 boundary geometry features for SATIM synthetic boundary candidates."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot
from typing import Any, Iterable, Mapping, Sequence, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class BoundaryGeometryFeatures:
    """Normalized geometry-only scores for one candidate boundary."""

    straightness: float
    orthogonality: float
    boundary_length: float
    segment_count: int


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def bearing_deg(a: Point, b: Point) -> float:
    """Return planar bearing in degrees for local candidate geometry."""
    return (degrees(atan2(b[1] - a[1], b[0] - a[0])) + 360.0) % 360.0


def angular_difference_deg(a: float, b: float) -> float:
    """Smallest angle difference between two bearings."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def polyline_length(points: Sequence[Point]) -> float:
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def straightness_from_points(points: Sequence[Point]) -> float:
    """Score straightness as endpoint distance divided by path length."""
    if len(points) < 2:
        return 0.0
    path_length = polyline_length(points)
    if path_length <= 0:
        return 0.0
    direct = hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
    return clamp01(direct / path_length)


def orthogonality_from_bearings(bearings: Iterable[float], tolerance_deg: float = 12.0) -> float:
    """Score whether any consecutive bearing pair is close to a 90 degree turn.

    This is intentionally weak evidence. It is useful for analysis but can be
    produced by roads, buildings, aprons, ports, parcels, and urban grids.
    """
    values = list(bearings)
    if len(values) < 2:
        return 0.0
    best = 0.0
    for incoming, outgoing in zip(values, values[1:]):
        error = abs(angular_difference_deg(incoming, outgoing) - 90.0)
        best = max(best, clamp01(1.0 - error / tolerance_deg))
    return best


def compute_boundary_geometry_features(row: Mapping[str, Any]) -> BoundaryGeometryFeatures:
    """Generate L0 geometry scores from candidate metadata.

    The function accepts either precomputed normalized columns or a compact
    coordinate string in ``boundary_points`` formatted as ``x:y;x:y;x:y``.
    """
    if "straightness" in row:
        straightness = clamp01(as_float(row.get("straightness")))
    else:
        straightness = clamp01(as_float(row.get("straight_boundary_score")))

    orthogonality = clamp01(as_float(row.get("orthogonality"), as_float(row.get("orthogonal_score"))))
    length = as_float(row.get("boundary_length"), as_float(row.get("boundary_length_m")))
    segment_count = int(as_float(row.get("segment_count"), 0))

    points_raw = str(row.get("boundary_points", "") or "").strip()
    if points_raw:
        points: list[Point] = []
        for token in points_raw.split(";"):
            if not token.strip():
                continue
            x_text, y_text = token.split(":", 1)
            points.append((float(x_text), float(y_text)))
        if points:
            straightness = straightness_from_points(points)
            length = polyline_length(points)
            segment_count = max(0, len(points) - 1)
            bearings = [bearing_deg(a, b) for a, b in zip(points, points[1:])]
            orthogonality = orthogonality_from_bearings(bearings)

    return BoundaryGeometryFeatures(
        straightness=clamp01(straightness),
        orthogonality=clamp01(orthogonality),
        boundary_length=max(0.0, length),
        segment_count=max(0, segment_count),
    )
