"""Validation helpers for provisional image-pixel field segmentation fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Point = tuple[float, float]
Polygon = list[Point]


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _proper_segment_intersection(
    a: Point,
    b: Point,
    c: Point,
    d: Point,
) -> bool:
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    return ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0))


def _point_in_polygon_strict(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        on_segment = (
            _orient(a, b, point) == 0
            and min(a[0], b[0]) <= x <= max(a[0], b[0])
            and min(a[1], b[1]) <= y <= max(a[1], b[1])
        )
        if on_segment:
            return False
        if (a[1] > y) != (b[1] > y):
            x_intersection = (
                (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            )
            if x < x_intersection:
                inside = not inside
    return inside


def _polygon_interiors_overlap(a: Polygon, b: Polygon) -> bool:
    for a_index in range(len(a)):
        for b_index in range(len(b)):
            if _proper_segment_intersection(
                a[a_index],
                a[(a_index + 1) % len(a)],
                b[b_index],
                b[(b_index + 1) % len(b)],
            ):
                return True
    return any(_point_in_polygon_strict(point, b) for point in a) or any(
        _point_in_polygon_strict(point, a) for point in b
    )


def validate_segmentation(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_width: int,
    expected_height: int,
) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    blockers: list[str] = []

    if raw.get("schema_version") != "satim.landscape.segmentation.v0.1":
        blockers.append("unsupported segmentation schema")
    if raw.get("fixture_id") != "SATIM-LANDSCAPE-C654-001":
        blockers.append("unexpected fixture_id")

    image = raw.get("image") or {}
    if image.get("sha256") != expected_sha256:
        blockers.append("segmentation raw SHA256 mismatch")
    if (
        image.get("width_px") != expected_width
        or image.get("height_px") != expected_height
    ):
        blockers.append("segmentation image dimensions mismatch")
    if raw.get("coordinate_system") != "IMAGE_PIXEL_XY_ORIGIN_TOP_LEFT":
        blockers.append("unexpected coordinate system")

    features = list(raw.get("features") or [])
    feature_ids: list[str] = []
    fields: list[tuple[str, Polygon]] = []

    for feature in features:
        fixture_feature_id = str(feature.get("id") or "")
        feature_ids.append(fixture_feature_id)
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = (geometry.get("coordinates") or [[]])[0]

        if geometry.get("type") != "Polygon" or len(coordinates) < 4:
            blockers.append(f"invalid polygon {fixture_feature_id}")
            continue
        if coordinates[0] != coordinates[-1]:
            blockers.append(f"polygon not closed {fixture_feature_id}")

        polygon: Polygon = []
        for coordinate in coordinates:
            if len(coordinate) != 2:
                blockers.append(
                    f"invalid coordinate arity {fixture_feature_id}"
                )
                continue
            x, y = coordinate
            if not (0 <= x < expected_width and 0 <= y < expected_height):
                blockers.append(
                    f"coordinate out of bounds {fixture_feature_id}"
                )
            polygon.append((float(x), float(y)))

        if properties.get("class") == "CULTIVATED_FIELD" and polygon:
            fields.append((fixture_feature_id, polygon[:-1]))

    if any(not feature_id for feature_id in feature_ids):
        blockers.append("segmentation feature without id")
    if len(feature_ids) != len(set(feature_ids)):
        blockers.append("segmentation feature id uniqueness failed")
    if len(fields) != 7:
        blockers.append(
            f"expected 7 CULTIVATED_FIELD instances, found {len(fields)}"
        )

    overlaps: list[tuple[str, str]] = []
    for index, (first_id, first_polygon) in enumerate(fields):
        for second_id, second_polygon in fields[index + 1 :]:
            if _polygon_interiors_overlap(first_polygon, second_polygon):
                overlaps.append((first_id, second_id))
    if overlaps:
        blockers.append(f"field polygon interiors overlap: {overlaps!r}")

    return {
        "status": "PASS" if not blockers else "FAIL",
        "field_instance_count": len(fields),
        "feature_count": len(features),
        "blockers": blockers,
        "annotation_status": raw.get("annotation_status"),
        "segmentation_completeness": raw.get("segmentation_completeness"),
        "known_omissions": list(raw.get("known_omissions") or ()),
    }
