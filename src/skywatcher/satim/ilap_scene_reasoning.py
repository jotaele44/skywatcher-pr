"""Fail-closed ILAP visual scene reasoning primitives.

This module intentionally does not perform pixel detection. It consumes measured
scene features from SATIM detector modules and produces deterministic derived
metrics plus an inspectable ILAP feature vector. Composite scoring is disabled
unless a calibrated versioned weight set is supplied by the caller.

ILAP = Infrastructure-Linked Airspace Point. Outputs are review-priority
objects only and never establish hidden infrastructure, purpose, mission,
wrongdoing, underground facilities, ownership, or causal linkage.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite

ILAP_COMPONENTS = (
    "visual_structure_score",
    "layout_unusualness_score",
    "accessibility_friction_score",
    "vehicle_activity_anomaly_score",
    "hydrologic_context_score",
    "terrain_context_score",
    "infrastructure_connectivity_score",
    "temporal_change_score",
    "source_corroboration_score",
)


@dataclass(frozen=True)
class AccessibilityInputs:
    straight_line_distance_m: float | None = None
    network_travel_distance_m: float | None = None
    road_access_count: int | None = None
    driveway_count: int | None = None
    mean_slope_deg: float | None = None
    local_relief_m: float | None = None
    bridge_dependency: bool | None = None
    barrier_count: int | None = None
    settlement_density: float | None = None


@dataclass(frozen=True)
class VehicleBaseline:
    observed_count: int | None
    comparison_counts: tuple[int, ...] = ()


@dataclass(frozen=True)
class IlapFeatureVector:
    components: Mapping[str, float | None]
    composite_score: float | None
    composite_state: str
    review_state: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _valid_number(value: float | int | None) -> bool:
    return value is not None and isfinite(float(value))


def network_detour_ratio(inputs: AccessibilityInputs) -> float | None:
    """Return network/straight-line distance ratio when both are valid.

    UNKNOWN is represented by ``None``. Invalid or zero straight-line distances
    do not silently become zero.
    """
    if not _valid_number(inputs.straight_line_distance_m):
        return None
    if not _valid_number(inputs.network_travel_distance_m):
        return None
    straight = float(inputs.straight_line_distance_m)
    network = float(inputs.network_travel_distance_m)
    if straight <= 0 or network < 0:
        return None
    return network / straight


def vehicle_count_summary(baseline: VehicleBaseline) -> dict[str, float | int | None | str]:
    """Describe a vehicle count without inventing an anomaly threshold.

    A comparison population is mandatory for contextual anomaly claims. The
    function returns robust descriptive statistics only; it never infers
    unusual activity, purpose, mission, or wrongdoing.
    """
    observed = baseline.observed_count
    counts = sorted(int(v) for v in baseline.comparison_counts if int(v) >= 0)
    if observed is None:
        return {
            "observed_count": None,
            "comparison_n": len(counts),
            "comparison_median": None,
            "comparison_q1": None,
            "comparison_q3": None,
            "anomaly_state": "ABSTAIN_INSUFFICIENT_EVIDENCE",
        }
    if not counts:
        return {
            "observed_count": int(observed),
            "comparison_n": 0,
            "comparison_median": None,
            "comparison_q1": None,
            "comparison_q3": None,
            "anomaly_state": "CALIBRATION_REQUIRED",
        }

    def percentile(sorted_values: list[int], fraction: float) -> float:
        if len(sorted_values) == 1:
            return float(sorted_values[0])
        pos = (len(sorted_values) - 1) * fraction
        lo = int(pos)
        hi = min(lo + 1, len(sorted_values) - 1)
        weight = pos - lo
        return float(sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight)

    return {
        "observed_count": int(observed),
        "comparison_n": len(counts),
        "comparison_median": percentile(counts, 0.5),
        "comparison_q1": percentile(counts, 0.25),
        "comparison_q3": percentile(counts, 0.75),
        "anomaly_state": "DESCRIPTIVE_BASELINE_ONLY",
    }


def build_ilap_feature_vector(
    components: Mapping[str, float | None],
    *,
    calibrated_weights: Mapping[str, float] | None = None,
    weight_set_id: str | None = None,
) -> IlapFeatureVector:
    """Build a decomposed ILAP feature vector with optional calibrated composite.

    Missing components remain ``None``. A composite is emitted only if every
    canonical component is present and a complete calibrated weight set plus a
    version identifier are supplied. Scores are relative discovery scores, not
    probabilities or identity evidence.
    """
    normalized: dict[str, float | None] = {}
    reasons: list[str] = []
    for name in ILAP_COMPONENTS:
        value = components.get(name)
        if value is None:
            normalized[name] = None
            reasons.append(f"MISSING:{name}")
            continue
        number = float(value)
        if not isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"{name} must be within [0,1] or None")
        normalized[name] = number

    if calibrated_weights is None or not weight_set_id:
        return IlapFeatureVector(
            components=normalized,
            composite_score=None,
            composite_state="CALIBRATION_REQUIRED",
            review_state="REVIEW_UNRESOLVED" if reasons else "REVIEW_REQUIRED",
            reasons=tuple(reasons + ["NO_CALIBRATED_WEIGHT_SET"]),
        )

    missing_weights = [name for name in ILAP_COMPONENTS if name not in calibrated_weights]
    missing_values = [name for name, value in normalized.items() if value is None]
    if missing_weights or missing_values:
        reasons.extend(f"MISSING_WEIGHT:{name}" for name in missing_weights)
        reasons.extend(f"MISSING_VALUE:{name}" for name in missing_values)
        return IlapFeatureVector(
            components=normalized,
            composite_score=None,
            composite_state="ABSTAIN_INSUFFICIENT_EVIDENCE",
            review_state="REVIEW_UNRESOLVED",
            reasons=tuple(reasons),
        )

    weights = {name: float(calibrated_weights[name]) for name in ILAP_COMPONENTS}
    if any(not isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("calibrated weights must be finite and non-negative")
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("calibrated weights must have positive total weight")

    composite = sum(float(normalized[name]) * weights[name] for name in ILAP_COMPONENTS) / total_weight
    return IlapFeatureVector(
        components=normalized,
        composite_score=composite,
        composite_state=f"CALIBRATED_DISCOVERY_SCORE:{weight_set_id}",
        review_state="REVIEW_REQUIRED",
        reasons=tuple(reasons),
    )
