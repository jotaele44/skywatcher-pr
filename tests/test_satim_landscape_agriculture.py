from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from skywatcher.satim.landscape.benchmark import (
    EXPECTED_COMPETING_CLASSES,
    evaluate_benchmark_manifest,
    evaluate_predictions,
)
from skywatcher.satim.landscape.calibration import CalibrationRecord, calibrate_profile
from skywatcher.satim.landscape.classifier import assess_image, classify_metrics
from skywatcher.satim.landscape.extractor import extract_landscape_metrics
from skywatcher.satim.landscape.models import CalibrationProfile, LandscapeMetrics
from skywatcher.satim.landscape.segmentation import validate_segmentation

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/satim_landscape/fixtures/C654/raw/Flight_C654.jpeg"
SEG = ROOT / "data/satim_landscape/fixtures/C654/segmentation.v0.1.geojson"
SHA = "a8b08e249f6ede4048563c892aba9b1ae6edb5e6d1c2f849421a3d8c285a9030"
RAW_REQUIRED = pytest.mark.skipif(
    not RAW.is_file(),
    reason="exact C654 raw bytes are not yet materialized on the GitHub branch",
)


def test_c654_segmentation_remains_provisional_seven_field_instances():
    report = validate_segmentation(
        SEG,
        expected_sha256=SHA,
        expected_width=1001,
        expected_height=1536,
    )
    assert report["status"] == "PASS"
    assert report["field_instance_count"] == 7
    assert report["annotation_status"] == "PROVISIONAL_HUMAN_ANNOTATION"


@RAW_REQUIRED
def test_c654_exact_bytes():
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == SHA


@RAW_REQUIRED
def test_positive_only_calibration_is_empirical_and_nonproduction():
    metrics = extract_landscape_metrics(RAW)
    profile = calibrate_profile(
        "seed",
        [CalibrationRecord("C654", SHA, "AGRICULTURAL_MOSAIC", "CALIBRATION", metrics)],
    )
    assert profile.status == "PROVISIONAL_POSITIVE_ONLY"
    assert not profile.production_validated
    assert profile.min_evidence_families == 5
    assert profile.thresholds["forest_matrix_fraction"] == metrics.forest_matrix_fraction
    assert profile.blockers


@RAW_REQUIRED
def test_no_calibration_fails_closed_and_retains_null_competitors():
    result = assess_image(RAW)
    assert result.terminal_state == "UNRESOLVED"
    assert result.top_class is None
    assert result.independent_positive_evidence_count == 0
    vector = {candidate.class_name: candidate.score for candidate in result.competing_classes}
    assert set(EXPECTED_COMPETING_CLASSES) <= set(vector)
    assert vector["AGRICULTURAL_MOSAIC"] is None


def _profile(threshold: float = 0.5, minimum: int = 4) -> CalibrationProfile:
    return CalibrationProfile(
        "synthetic",
        "CALIBRATED",
        "test",
        {
            "forest_matrix_fraction": threshold,
            "open_surface_fraction": threshold,
            "exposed_soil_fraction": threshold,
            "bright_cover_fraction": threshold,
            "directional_texture_score": threshold,
            "patch_mosaic_score": threshold,
        },
        minimum,
    )


def _metrics(**overrides):
    values = {
        "width_px": 10,
        "height_px": 10,
        "analysis_width_px": 10,
        "analysis_height_px": 10,
        "vegetation_fraction": 0,
        "forest_matrix_fraction": 0,
        "open_surface_fraction": 0,
        "exposed_soil_fraction": 0,
        "bright_cover_fraction": 0,
        "directional_texture_score": 0,
        "patch_mosaic_score": 0,
        "extraction_method": "test",
        "extraction_constants": {},
    }
    values.update(overrides)
    return LandscapeMetrics(**values)


def test_color_clearing_or_shape_like_signal_cannot_promote_alone():
    profile = _profile(0.5, 4)
    cases = [
        _metrics(bright_cover_fraction=1),
        _metrics(open_surface_fraction=1),
        _metrics(patch_mosaic_score=1),
    ]
    for index, metrics in enumerate(cases):
        result = classify_metrics(
            metrics,
            source_sha256="0" * 64,
            source_path=str(index),
            calibration=profile,
        )
        assert result.terminal_state != "CANDIDATE_NOT_IDENTITY"
        assert result.independent_positive_evidence_count == 1


@RAW_REQUIRED
def test_temporal_recurrence_never_increases_independent_evidence_count():
    metrics = extract_landscape_metrics(RAW)
    profile = calibrate_profile(
        "seed",
        [CalibrationRecord("C654", SHA, "AGRICULTURAL_MOSAIC", "CALIBRATION", metrics)],
    )
    without_temporal = classify_metrics(
        metrics,
        source_sha256=SHA,
        source_path="x",
        calibration=profile,
        temporal_recurrence=False,
    )
    with_temporal = classify_metrics(
        metrics,
        source_sha256=SHA,
        source_path="x",
        calibration=profile,
        temporal_recurrence=True,
    )
    assert without_temporal.independent_positive_evidence_count == 5
    assert with_temporal.independent_positive_evidence_count == 5
    assert with_temporal.temporal_recurrence_support is True


def test_tied_top_evidence_is_review_unresolved():
    result = classify_metrics(
        _metrics(),
        source_sha256="0" * 64,
        source_path="x",
        calibration=_profile(0.5, 1),
    )
    assert result.terminal_state == "REVIEW_UNRESOLVED"
    assert result.top_class is None


def test_current_benchmark_denominator_is_blocked_closed():
    state = evaluate_benchmark_manifest(
        ROOT / "data/satim_landscape/benchmark_manifest_v0_2.json"
    )
    assert state.status == "BLOCKED"
    assert not state.production_promotion_authorized
    assert state.fixture_count == 1
    assert state.verified_count == 0
    assert state.holdout_count == 0
    assert any("HOLDOUT" in blocker or "coverage" in blocker for blocker in state.blockers)


def test_source_registry_is_12_of_12_but_does_not_count_as_fixtures():
    path = ROOT / "data/satim_landscape/negative_control_source_registry_v0_1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["required_class_count"] == data["source_entry_count"] == 12
    assert data["benchmark_counting_entries"] == 0
    assert {entry["class"] for entry in data["entries"]} == (
        set(EXPECTED_COMPETING_CLASSES) - {"AGRICULTURAL_MOSAIC"}
    )


def test_prediction_arithmetic_and_production_gate():
    assessment = {
        "terminal_state": "CANDIDATE_NOT_IDENTITY",
        "top_class": "AGRICULTURAL_MOSAIC",
        "competing_classes": [
            {
                "class_name": name,
                "score": 1.0 if name == "AGRICULTURAL_MOSAIC" else None,
            }
            for name in EXPECTED_COMPETING_CLASSES
        ],
    }
    report = evaluate_predictions(
        [{"truth_class": "AGRICULTURAL_MOSAIC", "assessment": assessment}],
        calibration_status="PROVISIONAL_POSITIVE_ONLY",
    )
    assert report.tp == 1
    assert report.fp == report.tn == report.fn == 0
    assert report.status == "BLOCKED"
    assert "VALIDATED" in " ".join(report.blockers)


def test_satim_landscape_modules_do_not_import_flight_domains():
    for name in (
        "classifier.py",
        "calibration.py",
        "benchmark.py",
        "extractor.py",
        "segmentation.py",
    ):
        text = (ROOT / "src/skywatcher/satim/landscape" / name).read_text().lower()
        assert "from skywatcher.fpim" not in text
        assert "from skywatcher.corrim" not in text
        assert "fr24_route" not in text
