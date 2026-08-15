"""Local shadow photometry for SATIM imagery analysis.

This module measures what is actually present in source pixels. It does not
classify a dark region as a shadow by itself; the resulting measurements feed
``assess_shadow`` where geometry, direction and registered thresholds are
combined fail-closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from PIL import Image

from .visual_reasoning_runtime import ParameterSet, ShadowObservation

BBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class ShadowPhotometryMeasurement:
    region_mean_luminance: float
    reference_mean_luminance: float
    darkness_ratio: float
    local_shadow_median_luminance: float | None
    local_deviation: float | None
    region_texture: float
    reference_texture: float
    texture_retention: float
    clipped_black_ratio: float
    region_area_px: int
    reference_area_px: int


def _validate_bbox(image: Image.Image, bbox: BBox) -> BBox:
    left, top, right, bottom = bbox
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("bbox must be non-empty and contained within the image")
    return bbox


def _luminance(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    # Rec.709/sRGB relative-luminance coefficients are color-space constants,
    # not output-promotion thresholds.
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _luminances(image: Image.Image, bbox: BBox) -> tuple[list[float], int, int]:
    left, top, right, bottom = _validate_bbox(image, bbox)
    rgb = image.convert("RGB")
    values: list[float] = []
    black = 0
    total = 0
    pixels = rgb.load()
    for y in range(top, bottom):
        for x in range(left, right):
            value = _luminance(pixels[x, y])
            values.append(value)
            total += 1
            if value == 0.0:
                black += 1
    return values, black, total


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot measure an empty pixel set")
    return sum(values) / len(values)


def _texture(image: Image.Image, bbox: BBox) -> float:
    left, top, right, bottom = _validate_bbox(image, bbox)
    rgb = image.convert("RGB")
    pixels = rgb.load()
    differences: list[float] = []
    for y in range(top, bottom):
        for x in range(left, right):
            current = _luminance(pixels[x, y])
            if x + 1 < right:
                differences.append(abs(current - _luminance(pixels[x + 1, y])))
            if y + 1 < bottom:
                differences.append(abs(current - _luminance(pixels[x, y + 1])))
    if not differences:
        return 0.0
    return _mean(differences) / 255.0


def _expanded_bbox(image: Image.Image, bbox: BBox, radius: int) -> BBox:
    left, top, right, bottom = bbox
    return (
        max(0, left - radius),
        max(0, top - radius),
        min(image.width, right + radius),
        min(image.height, bottom + radius),
    )


def _reference_luminances(image: Image.Image, bbox: BBox, radius: int) -> list[float]:
    outer = _expanded_bbox(image, bbox, radius)
    left, top, right, bottom = bbox
    o_left, o_top, o_right, o_bottom = outer
    rgb = image.convert("RGB")
    pixels = rgb.load()
    values: list[float] = []
    for y in range(o_top, o_bottom):
        for x in range(o_left, o_right):
            if left <= x < right and top <= y < bottom:
                continue
            values.append(_luminance(pixels[x, y]))
    if not values:
        raise ValueError("reference ring is empty; provide a larger image or smaller target")
    return values


def measure_shadow_photometry(
    image: Image.Image,
    bbox: BBox,
    params: ParameterSet,
    *,
    nearby_shadow_bboxes: Sequence[BBox] = (),
) -> ShadowPhotometryMeasurement:
    """Measure local darkness and texture without deciding shadow identity."""

    required = params.require(
        "SHADOW.LOCAL_WINDOW_PX",
        "SHADOW.REFERENCE_RADIUS_PX",
    )
    if required is None:
        raise ValueError("missing SHADOW.LOCAL_WINDOW_PX or SHADOW.REFERENCE_RADIUS_PX")
    local_window, reference_radius = required
    radius = int(reference_radius)
    if radius <= 0 or local_window <= 0:
        raise ValueError("shadow photometry radii must be positive")

    target_values, black, area = _luminances(image, bbox)
    target_mean = _mean(target_values)
    reference_values = _reference_luminances(image, bbox, radius)
    reference_mean = _mean(reference_values)
    darkness_ratio = target_mean / reference_mean if reference_mean > 0.0 else 1.0

    nearby_means: list[float] = []
    for nearby_bbox in nearby_shadow_bboxes:
        values, _, _ = _luminances(image, nearby_bbox)
        nearby_means.append(_mean(values))
    local_shadow_median = median(nearby_means) if nearby_means else None
    local_deviation = (
        abs(target_mean - local_shadow_median) / 255.0
        if local_shadow_median is not None
        else None
    )

    region_texture = _texture(image, bbox)
    outer = _expanded_bbox(image, bbox, radius)
    reference_texture = _texture(image, outer)
    texture_retention = (
        min(1.0, region_texture / reference_texture)
        if reference_texture > 0.0
        else 1.0
    )

    return ShadowPhotometryMeasurement(
        region_mean_luminance=target_mean,
        reference_mean_luminance=reference_mean,
        darkness_ratio=darkness_ratio,
        local_shadow_median_luminance=local_shadow_median,
        local_deviation=local_deviation,
        region_texture=region_texture,
        reference_texture=reference_texture,
        texture_retention=texture_retention,
        clipped_black_ratio=black / area,
        region_area_px=area,
        reference_area_px=len(reference_values),
    )


def to_shadow_observation(
    measurement: ShadowPhotometryMeasurement,
    *,
    edge_consistency: float | None,
    direction_delta_deg: float | None,
    geometry_support: bool | None,
) -> ShadowObservation:
    """Combine measured photometry with independent geometric shadow evidence."""

    return ShadowObservation(
        darkness_ratio=measurement.darkness_ratio,
        local_deviation=measurement.local_deviation,
        texture_retention=measurement.texture_retention,
        edge_consistency=edge_consistency,
        direction_delta_deg=direction_delta_deg,
        clipped_black_ratio=measurement.clipped_black_ratio,
        geometry_support=geometry_support,
    )
