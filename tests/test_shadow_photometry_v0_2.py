from __future__ import annotations

from PIL import Image

from skywatcher.satim.shadow_photometry import (
    measure_shadow_photometry,
    to_shadow_observation,
)
from skywatcher.satim.visual_reasoning_runtime import ParameterSet, assess_shadow


def _params() -> ParameterSet:
    return ParameterSet(
        {
            "SHADOW.LOCAL_WINDOW_PX": 3.0,
            "SHADOW.REFERENCE_RADIUS_PX": 2.0,
            "SHADOW.DARKNESS_RATIO_MIN": 0.2,
            "SHADOW.DARKNESS_RATIO_MAX": 0.75,
            "SHADOW.LOCAL_DEVIATION_MAX": 0.2,
            "SHADOW.TEXTURE_RETENTION_MIN": 0.0,
            "SHADOW.DIRECTION_TOLERANCE_DEG": 20.0,
            "SHADOW.CLIPPED_BLACK_RATIO": 0.9,
        }
    )


def _synthetic_shadow_image() -> Image.Image:
    image = Image.new("RGB", (12, 8), (200, 200, 200))
    pixels = image.load()
    for y in range(2, 6):
        for x in range(3, 6):
            value = 80 + ((x + y) % 2) * 10
            pixels[x, y] = (value, value, value)
    for y in range(2, 6):
        for x in range(7, 10):
            value = 82 + ((x + y) % 2) * 10
            pixels[x, y] = (value, value, value)
    return image


def test_photometry_measures_relative_darkness_against_local_reference() -> None:
    image = _synthetic_shadow_image()
    measurement = measure_shadow_photometry(
        image,
        (3, 2, 6, 6),
        _params(),
        nearby_shadow_bboxes=((7, 2, 10, 6),),
    )
    assert 0.2 < measurement.darkness_ratio < 0.75
    assert measurement.local_deviation is not None
    assert measurement.local_deviation < 0.05
    assert measurement.region_area_px == 12
    assert measurement.reference_area_px > 0


def test_photometry_does_not_classify_without_independent_geometry() -> None:
    image = _synthetic_shadow_image()
    measurement = measure_shadow_photometry(
        image,
        (3, 2, 6, 6),
        _params(),
        nearby_shadow_bboxes=((7, 2, 10, 6),),
    )
    observation = to_shadow_observation(
        measurement,
        edge_consistency=0.9,
        direction_delta_deg=5.0,
        geometry_support=False,
    )
    result = assess_shadow(observation, _params())
    assert result.state != "PHYSICALLY_PLAUSIBLE_SHADOW"


def test_photometry_plus_geometry_can_support_shadow() -> None:
    image = _synthetic_shadow_image()
    measurement = measure_shadow_photometry(
        image,
        (3, 2, 6, 6),
        _params(),
        nearby_shadow_bboxes=((7, 2, 10, 6),),
    )
    observation = to_shadow_observation(
        measurement,
        edge_consistency=0.9,
        direction_delta_deg=5.0,
        geometry_support=True,
    )
    result = assess_shadow(observation, _params())
    assert result.state == "PHYSICALLY_PLAUSIBLE_SHADOW"


def test_exact_black_pixels_are_measured_separately_from_shadow_identity() -> None:
    image = Image.new("RGB", (8, 8), (200, 200, 200))
    pixels = image.load()
    for y in range(2, 6):
        for x in range(2, 6):
            pixels[x, y] = (0, 0, 0)
    measurement = measure_shadow_photometry(image, (2, 2, 6, 6), _params())
    assert measurement.clipped_black_ratio == 1.0
    assert measurement.darkness_ratio == 0.0
