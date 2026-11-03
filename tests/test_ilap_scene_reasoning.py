import pytest

from skywatcher.satim.ilap_scene_reasoning import (
    AccessibilityInputs,
    VehicleBaseline,
    build_ilap_feature_vector,
    network_detour_ratio,
    vehicle_count_summary,
)


def test_network_detour_ratio_preserves_unknown_and_computes_valid_ratio() -> None:
    assert network_detour_ratio(AccessibilityInputs()) is None
    assert network_detour_ratio(
        AccessibilityInputs(straight_line_distance_m=1000, network_travel_distance_m=8000)
    ) == 8.0
    assert network_detour_ratio(
        AccessibilityInputs(straight_line_distance_m=0, network_travel_distance_m=8000)
    ) is None


def test_vehicle_count_without_comparison_population_is_not_an_anomaly_claim() -> None:
    result = vehicle_count_summary(VehicleBaseline(observed_count=24))
    assert result["observed_count"] == 24
    assert result["comparison_n"] == 0
    assert result["anomaly_state"] == "CALIBRATION_REQUIRED"


def test_vehicle_baseline_returns_descriptive_statistics_only() -> None:
    result = vehicle_count_summary(
        VehicleBaseline(observed_count=24, comparison_counts=(2, 3, 4, 4, 5, 7, 8))
    )
    assert result["comparison_n"] == 7
    assert result["comparison_median"] == 4.0
    assert result["anomaly_state"] == "DESCRIPTIVE_BASELINE_ONLY"


def test_ilap_composite_is_disabled_without_calibrated_weights() -> None:
    components = {
        "visual_structure_score": 0.8,
        "layout_unusualness_score": 0.7,
        "accessibility_friction_score": 0.9,
        "vehicle_activity_anomaly_score": 0.6,
        "hydrologic_context_score": 0.5,
        "terrain_context_score": 0.8,
        "infrastructure_connectivity_score": 0.4,
        "temporal_change_score": 0.3,
        "source_corroboration_score": 0.7,
    }
    result = build_ilap_feature_vector(components)
    assert result.composite_score is None
    assert result.composite_state == "CALIBRATION_REQUIRED"
    assert "NO_CALIBRATED_WEIGHT_SET" in result.reasons


def test_missing_component_blocks_even_with_weight_set() -> None:
    components = {
        "visual_structure_score": 0.8,
        "layout_unusualness_score": None,
        "accessibility_friction_score": 0.9,
        "vehicle_activity_anomaly_score": 0.6,
        "hydrologic_context_score": 0.5,
        "terrain_context_score": 0.8,
        "infrastructure_connectivity_score": 0.4,
        "temporal_change_score": 0.3,
        "source_corroboration_score": 0.7,
    }
    weights = {name: 1.0 for name in components}
    result = build_ilap_feature_vector(
        components, calibrated_weights=weights, weight_set_id="test-only"
    )
    assert result.composite_score is None
    assert result.composite_state == "ABSTAIN_INSUFFICIENT_EVIDENCE"
    assert result.review_state == "REVIEW_UNRESOLVED"


def test_complete_explicit_weight_set_can_produce_discovery_score() -> None:
    components = {
        "visual_structure_score": 0.8,
        "layout_unusualness_score": 0.7,
        "accessibility_friction_score": 0.9,
        "vehicle_activity_anomaly_score": 0.6,
        "hydrologic_context_score": 0.5,
        "terrain_context_score": 0.8,
        "infrastructure_connectivity_score": 0.4,
        "temporal_change_score": 0.3,
        "source_corroboration_score": 0.7,
    }
    weights = {name: 1.0 for name in components}
    result = build_ilap_feature_vector(
        components, calibrated_weights=weights, weight_set_id="fixture-v1"
    )
    assert result.composite_score == pytest.approx(sum(components.values()) / len(components))
    assert result.composite_state == "CALIBRATED_DISCOVERY_SCORE:fixture-v1"
    assert result.review_state == "REVIEW_REQUIRED"


def test_component_outside_unit_interval_fails_closed() -> None:
    with pytest.raises(ValueError):
        build_ilap_feature_vector({"visual_structure_score": 1.2})
