import pytest

from skywatcher.satim.artifacts.annotation_binding import (
    AnnotationPrimitive,
    annotation_pixel_accounting,
    assert_pristine_measurement_source,
    summarize_positive_only_agreement,
)


def _roi(roi_id: str, color: str = "RED") -> AnnotationPrimitive:
    return AnnotationPrimitive(
        roi_id=roi_id,
        image_id="IMG_1",
        color=color,
        geometry={"type": "line"},
        annotation_pixels=10,
    )


def test_annotation_pixels_can_never_be_measurement_bytes():
    assert_pristine_measurement_source(
        pristine_sha256="raw",
        measurement_sha256="raw",
        annotation_sha256="markup",
    )
    with pytest.raises(ValueError, match="annotation bytes"):
        assert_pristine_measurement_source(
            pristine_sha256="same",
            measurement_sha256="same",
            annotation_sha256="same",
        )
    with pytest.raises(ValueError, match="pristine source"):
        assert_pristine_measurement_source(
            pristine_sha256="raw",
            measurement_sha256="different",
            annotation_sha256="markup",
        )


def test_positive_only_agreement_never_synthesizes_negatives():
    rows = [_roi("r1"), _roi("r2", "BLUE"), _roi("r3", "YELLOW")]
    result = summarize_positive_only_agreement(
        rows,
        {"r1": "SUPPORTED", "r2": "PARTIAL", "r3": "UNRESOLVED"},
    )
    assert result.denominator == 3
    assert result.supported == 1
    assert result.partial == 1
    assert result.unresolved == 1
    assert result.unmarked_policy == "UNKNOWN"
    assert result.arithmetic_closed
    assert not result.certification_ready


def test_missing_roi_result_fails_certification_but_closes_arithmetic():
    result = summarize_positive_only_agreement(
        [_roi("r1"), _roi("r2")],
        {"r1": "SUPPORTED"},
    )
    assert result.missing_results == 1
    assert result.arithmetic_closed
    assert not result.certification_ready


def test_unknown_machine_roi_fails_closed():
    with pytest.raises(ValueError, match="unknown ROI ids"):
        summarize_positive_only_agreement(
            [_roi("r1")],
            {"r1": "SUPPORTED", "r2": "SUPPORTED"},
        )


def test_pixel_accounting_requires_exact_closure():
    closed = annotation_pixel_accounting(
        detected_color_pixels=100,
        accepted_annotation_pixels=80,
        rejected_source_color_pixels=20,
    )
    assert closed["arithmetic_closed"]
    assert closed["unexplained_pixels"] == 0

    open_ = annotation_pixel_accounting(
        detected_color_pixels=100,
        accepted_annotation_pixels=79,
        rejected_source_color_pixels=20,
    )
    assert not open_["arithmetic_closed"]
    assert open_["unexplained_pixels"] == 1
