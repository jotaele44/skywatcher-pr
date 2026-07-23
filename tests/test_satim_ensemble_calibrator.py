from copy import deepcopy

from satim_ensemble_calibrator import (
    CalibrationClass,
    CalibrationSample,
    DetectorCalibrationInput,
    DetectorType,
    DETECTOR_PROVENANCE_SEPARATION,
    NO_CROSS_DETECTOR_FACT_SYNTHESIS,
    ORIGINAL_CLASSIFICATION_PRESERVATION,
    ORIGINAL_SCORE_PRESERVATION,
    build_calibration_ledger,
    build_calibration_reliability_report,
    build_detector_calibration_patch,
    build_human_review_queue,
    calibrate_detector,
    calibration_bin,
    ensemble_calibrator_schema,
)


def sample(
    detector: DetectorType,
    record_id: str,
    score: float,
    outcome: float,
) -> CalibrationSample:
    return CalibrationSample(
        detector=detector,
        record_id=record_id,
        original_classification="VISIBLE_FEATURE",
        detector_score=score,
        observed_outcome=outcome,
        provenance={"source": detector.value, "record_id": record_id},
        epoch_id="EPOCH-001",
    )


def fixture(kind: str) -> DetectorCalibrationInput:
    detector = DetectorType.PATCHWORK_POI
    if kind == "well":
        values = [(0.82, 0.8), (0.84, 0.8), (0.86, 1.0), (0.88, 0.8), (0.89, 1.0)]
    elif kind == "overconfident":
        values = [(0.82, 0.2), (0.84, 0.2), (0.86, 0.4), (0.88, 0.4), (0.89, 0.4)]
    elif kind == "underconfident":
        values = [(0.42, 0.8), (0.44, 0.8), (0.46, 1.0), (0.48, 0.8), (0.49, 1.0)]
    elif kind == "insufficient":
        values = [(0.82, 0.8), (0.84, 0.8)]
    elif kind == "drift":
        values = [(0.82, 0.2), (0.84, 0.2), (0.86, 0.4), (0.88, 0.4), (0.89, 0.4)]
    else:
        raise ValueError(kind)

    return DetectorCalibrationInput(
        detector=detector,
        samples=tuple(sample(detector, f"REC-{index:02d}", score, outcome) for index, (score, outcome) in enumerate(values)),
        prior_expected_accuracy=0.85 if kind == "drift" else None,
        prior_sample_support=20 if kind == "drift" else 0,
        drift_threshold=0.15,
        minimum_support=5,
    )


def test_schema_contract_and_guardrails():
    schema = ensemble_calibrator_schema()
    assert schema["calibrator"] == "SATIM_DETECTOR_ENSEMBLE_CALIBRATOR_v1"
    assert set(schema["detectors"]) == {item.value for item in DetectorType}
    assert set(schema["classes"]) == {item.value for item in CalibrationClass}
    assert schema["guardrails"] == [
        ORIGINAL_SCORE_PRESERVATION,
        ORIGINAL_CLASSIFICATION_PRESERVATION,
        DETECTOR_PROVENANCE_SEPARATION,
        NO_CROSS_DETECTOR_FACT_SYNTHESIS,
    ]
    assert "SOURCE_SCORE_MUTATION" in schema["prohibited_outputs"]
    assert "CROSS_DETECTOR_FACT_SYNTHESIS" in schema["prohibited_outputs"]


def test_deterministic_binning_boundaries():
    assert calibration_bin(0.0) == ("BIN_00_00_10", 0.0, 0.1)
    assert calibration_bin(0.55) == ("BIN_05_50_60", 0.5, 0.6)
    assert calibration_bin(1.0) == ("BIN_09_90_100", 0.9, 1.0)
    assert calibration_bin(-1.0) == calibration_bin(0.0)
    assert calibration_bin(2.0) == calibration_bin(1.0)


def test_required_calibration_classes_are_emitted():
    assert calibrate_detector(fixture("well"))[0].classification == "WELL_CALIBRATED"
    assert calibrate_detector(fixture("overconfident"))[0].classification == "OVERCONFIDENT"
    assert calibrate_detector(fixture("underconfident"))[0].classification == "UNDERCONFIDENT"
    assert calibrate_detector(fixture("insufficient"))[0].classification == "INSUFFICIENT_SUPPORT"
    assert calibrate_detector(fixture("drift"))[0].classification == "DRIFT_REVIEW_REQUIRED"


def test_original_outputs_are_immutable_and_provenance_is_separate():
    source = fixture("overconfident")
    before = deepcopy(source)
    ledger = build_calibration_ledger([source])
    assert source == before
    assert len(ledger) == 1
    rows = ledger[0]["source_samples"]
    assert [row["original_score"] for row in rows] == [item.detector_score for item in source.samples]
    assert [row["original_classification"] for row in rows] == [item.original_classification for item in source.samples]
    assert all(row["provenance"] for row in rows)
    assert DETECTOR_PROVENANCE_SEPARATION in ledger[0]["guardrails"]


def test_calibration_patch_is_non_destructive_and_monotonic():
    detector = DetectorType.WATER_FEATURE
    source = DetectorCalibrationInput(
        detector=detector,
        samples=(
            sample(detector, "A", 0.15, 0.2),
            sample(detector, "B", 0.25, 0.1),
            sample(detector, "C", 0.35, 0.8),
            sample(detector, "D", 0.45, 0.5),
            sample(detector, "E", 0.55, 0.9),
        ),
        minimum_support=1,
    )
    patches = build_detector_calibration_patch([source])
    calibrated = [row["calibrated_score"] for row in patches]
    assert calibrated == sorted(calibrated)
    for row, original in zip(patches, sorted(source.samples, key=lambda item: item.detector_score)):
        assert row["record_id"] == original.record_id
        assert row["original_score"] == original.detector_score
        assert row["original_classification"] == original.original_classification
        assert row["mutation_rule"] == "source detector output retained; emit calibration patch only"


def test_determinism_bounded_metrics_and_reliability_report():
    source = fixture("well")
    first = calibrate_detector(source)
    second = calibrate_detector(source)
    assert first == second
    result = first[0]
    assert 0.0 <= result.expected_accuracy <= 1.0
    assert 0.0 <= result.observed_accuracy <= 1.0
    assert -1.0 <= result.reliability_gap <= 1.0
    assert 0.0 <= result.drift_signal <= 1.0
    report = build_calibration_reliability_report([source])[0]
    assert report["detector"] == DetectorType.PATCHWORK_POI.value
    assert report["sample_support"] == 5
    assert 0.0 <= report["mean_absolute_reliability_gap"] <= 1.0


def test_review_queue_handles_support_and_drift():
    queue = build_human_review_queue([fixture("insufficient"), fixture("drift")])
    assert len(queue) == 2
    assert queue[0]["classification"] == "INSUFFICIENT_SUPPORT"
    assert queue[0]["priority"] == "MEDIUM"
    assert queue[1]["classification"] == "DRIFT_REVIEW_REQUIRED"
    assert queue[1]["priority"] == "HIGH"
    assert all(row["guardrail"] == NO_CROSS_DETECTOR_FACT_SYNTHESIS for row in queue)


def test_all_detector_inputs_are_supported_without_fact_synthesis():
    schema = ensemble_calibrator_schema()
    expected = {
        "PATCHWORK_POI",
        "ROAD_END_NODE",
        "CUT_FILL_FEATURE",
        "LINEAR_CORRIDOR",
        "WATER_FEATURE",
        "ARTIFACT_CONFIDENCE_PATCH",
        "CONTRADICTION_LEDGER",
        "TEMPORAL_CHANGE_LEDGER",
    }
    assert set(schema["detectors"]) == expected
    assert NO_CROSS_DETECTOR_FACT_SYNTHESIS in schema["guardrails"]
