from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DetectorType(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    LINEAR_CORRIDOR = "LINEAR_CORRIDOR"
    WATER_FEATURE = "WATER_FEATURE"
    ARTIFACT_CONFIDENCE_PATCH = "ARTIFACT_CONFIDENCE_PATCH"
    CONTRADICTION_LEDGER = "CONTRADICTION_LEDGER"
    TEMPORAL_CHANGE_LEDGER = "TEMPORAL_CHANGE_LEDGER"


class CalibrationClass(str, Enum):
    WELL_CALIBRATED = "WELL_CALIBRATED"
    OVERCONFIDENT = "OVERCONFIDENT"
    UNDERCONFIDENT = "UNDERCONFIDENT"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    DRIFT_REVIEW_REQUIRED = "DRIFT_REVIEW_REQUIRED"


NO_CROSS_DETECTOR_FACT_SYNTHESIS = "NO_CROSS_DETECTOR_FACT_SYNTHESIS"
ORIGINAL_SCORE_PRESERVATION = "ORIGINAL_SCORE_PRESERVATION"
ORIGINAL_CLASSIFICATION_PRESERVATION = "ORIGINAL_CLASSIFICATION_PRESERVATION"
DETECTOR_PROVENANCE_SEPARATION = "DETECTOR_PROVENANCE_SEPARATION"


@dataclass(frozen=True)
class CalibrationSample:
    detector: DetectorType | str
    record_id: str
    original_classification: str
    detector_score: float
    observed_outcome: float
    provenance: dict[str, Any] = field(default_factory=dict)
    epoch_id: str = ""


@dataclass(frozen=True)
class DetectorCalibrationInput:
    detector: DetectorType | str
    samples: tuple[CalibrationSample, ...]
    prior_expected_accuracy: float | None = None
    prior_sample_support: int = 0
    drift_threshold: float = 0.15
    minimum_support: int = 5


@dataclass(frozen=True)
class CalibrationBinResult:
    detector: str
    calibration_bin: str
    lower_bound: float
    upper_bound: float
    expected_accuracy: float
    observed_accuracy: float
    reliability_gap: float
    sample_support: int
    classification: str
    drift_signal: float
    review_required: bool
    review_reasons: tuple[str, ...]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def calibration_bin(score: float) -> tuple[str, float, float]:
    value = clamp01(score)
    index = min(9, int(value * 10.0))
    lower = index / 10.0
    upper = (index + 1) / 10.0
    return f"BIN_{index:02d}_{int(lower * 100):02d}_{int(upper * 100):02d}", lower, upper


def _group_samples(samples: tuple[CalibrationSample, ...]) -> dict[str, list[CalibrationSample]]:
    groups: dict[str, list[CalibrationSample]] = {}
    for sample in samples:
        name, _, _ = calibration_bin(sample.detector_score)
        groups.setdefault(name, []).append(sample)
    return groups


def _classify_gap(gap: float, support: int, minimum_support: int, drift_signal: float, drift_threshold: float) -> CalibrationClass:
    if support < minimum_support:
        return CalibrationClass.INSUFFICIENT_SUPPORT
    if drift_signal >= drift_threshold:
        return CalibrationClass.DRIFT_REVIEW_REQUIRED
    if gap >= 0.1:
        return CalibrationClass.OVERCONFIDENT
    if gap <= -0.1:
        return CalibrationClass.UNDERCONFIDENT
    return CalibrationClass.WELL_CALIBRATED


def calibrate_detector(calibration: DetectorCalibrationInput) -> list[CalibrationBinResult]:
    detector = _name(calibration.detector)
    groups = _group_samples(calibration.samples)
    rows: list[CalibrationBinResult] = []
    previous_calibrated = 0.0

    for bin_name in sorted(groups):
        samples = groups[bin_name]
        _, lower, upper = calibration_bin(samples[0].detector_score)
        expected = round(sum(clamp01(item.detector_score) for item in samples) / len(samples), 4)
        observed = round(sum(clamp01(item.observed_outcome) for item in samples) / len(samples), 4)
        raw_calibrated = observed
        calibrated = round(max(previous_calibrated, raw_calibrated), 4)
        previous_calibrated = calibrated
        gap = round(expected - observed, 4)

        if calibration.prior_expected_accuracy is None or calibration.prior_sample_support <= 0:
            drift = 0.0
        else:
            drift = round(abs(observed - clamp01(calibration.prior_expected_accuracy)), 4)

        classification = _classify_gap(
            gap,
            len(samples),
            calibration.minimum_support,
            drift,
            clamp01(calibration.drift_threshold),
        )
        reasons: list[str] = []
        if len(samples) < calibration.minimum_support:
            reasons.append("INSUFFICIENT_SAMPLE_SUPPORT")
        if drift >= clamp01(calibration.drift_threshold):
            reasons.append("CALIBRATION_DRIFT_SIGNAL")
        if classification is CalibrationClass.OVERCONFIDENT:
            reasons.append("EXPECTED_EXCEEDS_OBSERVED")
        if classification is CalibrationClass.UNDERCONFIDENT:
            reasons.append("OBSERVED_EXCEEDS_EXPECTED")

        rows.append(
            CalibrationBinResult(
                detector=detector,
                calibration_bin=bin_name,
                lower_bound=lower,
                upper_bound=upper,
                expected_accuracy=expected,
                observed_accuracy=observed,
                reliability_gap=gap,
                sample_support=len(samples),
                classification=classification.value,
                drift_signal=drift,
                review_required=classification in {
                    CalibrationClass.INSUFFICIENT_SUPPORT,
                    CalibrationClass.DRIFT_REVIEW_REQUIRED,
                },
                review_reasons=tuple(sorted(set(reasons))),
            )
        )
    return rows


def ensemble_calibrator_schema() -> dict[str, Any]:
    return {
        "calibrator": "SATIM_DETECTOR_ENSEMBLE_CALIBRATOR_v1",
        "detectors": [item.value for item in DetectorType],
        "classes": [item.value for item in CalibrationClass],
        "fields": [
            "DETECTOR_SCORE",
            "CALIBRATED_SCORE",
            "CALIBRATION_BIN",
            "EXPECTED_ACCURACY",
            "OBSERVED_ACCURACY",
            "RELIABILITY_GAP",
            "DRIFT_SIGNAL",
            "SAMPLE_SUPPORT",
        ],
        "guardrails": [
            ORIGINAL_SCORE_PRESERVATION,
            ORIGINAL_CLASSIFICATION_PRESERVATION,
            DETECTOR_PROVENANCE_SEPARATION,
            NO_CROSS_DETECTOR_FACT_SYNTHESIS,
        ],
        "outputs": [
            "SATIM_CALIBRATION_LEDGER",
            "DETECTOR_CALIBRATION_PATCH",
            "CALIBRATION_RELIABILITY_REPORT",
            "HUMAN_REVIEW_QUEUE",
        ],
        "prohibited_outputs": [
            "SOURCE_SCORE_MUTATION",
            "SOURCE_CLASSIFICATION_MUTATION",
            "CROSS_DETECTOR_FACT_SYNTHESIS",
            "OWNERSHIP_INFERENCE",
            "PURPOSE_INFERENCE",
            "COORDINATION_INFERENCE",
            "HIDDEN_INFRASTRUCTURE_INFERENCE",
            "COVERT_ACTIVITY_INFERENCE",
        ],
    }


def _sample_row(sample: CalibrationSample) -> dict[str, Any]:
    return {
        "detector": _name(sample.detector),
        "record_id": sample.record_id,
        "original_classification": sample.original_classification,
        "original_score": clamp01(sample.detector_score),
        "observed_outcome": clamp01(sample.observed_outcome),
        "provenance": dict(sample.provenance),
        "epoch_id": sample.epoch_id,
    }


def build_calibration_ledger(inputs: list[DetectorCalibrationInput]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for calibration in inputs:
        results = calibrate_detector(calibration)
        grouped = _group_samples(calibration.samples)
        for result in results:
            rows.append(
                {
                    "detector": result.detector,
                    "calibration_bin": result.calibration_bin,
                    "expected_accuracy": result.expected_accuracy,
                    "observed_accuracy": result.observed_accuracy,
                    "reliability_gap": result.reliability_gap,
                    "drift_signal": result.drift_signal,
                    "sample_support": result.sample_support,
                    "classification": result.classification,
                    "source_samples": [_sample_row(item) for item in grouped[result.calibration_bin]],
                    "review_required": result.review_required,
                    "review_reasons": list(result.review_reasons),
                    "guardrails": [
                        ORIGINAL_SCORE_PRESERVATION,
                        ORIGINAL_CLASSIFICATION_PRESERVATION,
                        DETECTOR_PROVENANCE_SEPARATION,
                        NO_CROSS_DETECTOR_FACT_SYNTHESIS,
                    ],
                }
            )
    return rows


def build_detector_calibration_patch(inputs: list[DetectorCalibrationInput]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for calibration in inputs:
        result_by_bin = {item.calibration_bin: item for item in calibrate_detector(calibration)}
        previous = 0.0
        for sample in sorted(calibration.samples, key=lambda item: (clamp01(item.detector_score), item.record_id)):
            bin_name, _, _ = calibration_bin(sample.detector_score)
            result = result_by_bin[bin_name]
            calibrated = round(max(previous, result.observed_accuracy), 4)
            previous = calibrated
            rows.append(
                {
                    "detector": _name(sample.detector),
                    "record_id": sample.record_id,
                    "original_classification": sample.original_classification,
                    "original_score": clamp01(sample.detector_score),
                    "calibrated_score": calibrated,
                    "calibration_bin": bin_name,
                    "patch_status": "DETECTOR_CALIBRATION_PATCH",
                    "mutation_rule": "source detector output retained; emit calibration patch only",
                    "provenance": dict(sample.provenance),
                    "guardrail": NO_CROSS_DETECTOR_FACT_SYNTHESIS,
                }
            )
    return rows


def build_calibration_reliability_report(inputs: list[DetectorCalibrationInput]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for calibration in inputs:
        results = calibrate_detector(calibration)
        support = sum(item.sample_support for item in results)
        weighted_gap = 0.0 if support == 0 else sum(abs(item.reliability_gap) * item.sample_support for item in results) / support
        rows.append(
            {
                "detector": _name(calibration.detector),
                "bin_count": len(results),
                "sample_support": support,
                "mean_absolute_reliability_gap": round(weighted_gap, 4),
                "maximum_drift_signal": max((item.drift_signal for item in results), default=0.0),
                "review_bin_count": sum(1 for item in results if item.review_required),
                "guardrail": NO_CROSS_DETECTOR_FACT_SYNTHESIS,
            }
        )
    return rows


def build_human_review_queue(inputs: list[DetectorCalibrationInput]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for calibration in inputs:
        for result in calibrate_detector(calibration):
            if not result.review_required:
                continue
            rows.append(
                {
                    "detector": result.detector,
                    "calibration_bin": result.calibration_bin,
                    "classification": result.classification,
                    "priority": "HIGH" if result.classification == CalibrationClass.DRIFT_REVIEW_REQUIRED.value else "MEDIUM",
                    "review_reasons": list(result.review_reasons),
                    "sample_support": result.sample_support,
                    "drift_signal": result.drift_signal,
                    "guardrail": NO_CROSS_DETECTOR_FACT_SYNTHESIS,
                }
            )
    return rows
