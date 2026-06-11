import copy

import pytest

from fr24_allowed_enums import AllowedEnumRegistry, load_allowed_enum_registry
from fr24_config_defaults import ConfigDefaults, ConfigDefaultsError, load_config_defaults


def test_default_config_loads_against_default_registry():
    config = load_config_defaults()
    seam = config.signal_group_config("seam_anomaly_detection")

    assert seam.defaults["interpretation_guardrail"] == "artifact_only"
    assert config.suppression_multiplier("seam_anomaly_detection", "ordinary_tile_artifact") == 0.25
    assert config.suppression_multiplier("seam_anomaly_detection", "unknown_reason") == 1.0


def test_pipeline_order_matches_allowed_enum_registry():
    registry = load_allowed_enum_registry()
    config = load_config_defaults(registry=registry)

    assert config.pipeline_stage_order == registry.pipeline_stage_order
    assert config.pipeline_stage_order.index("tile_suppression") < config.pipeline_stage_order.index("ground_context")


def test_all_routed_scoring_signal_groups_have_defaults():
    registry = load_allowed_enum_registry()
    config = load_config_defaults(registry=registry)
    configured = {
        signal_group_id
        for threshold_group in config.threshold_groups.values()
        for signal_group_id in threshold_group["signal_groups"]
    }

    for signal_group_id, route in registry.signal_group_routes.items():
        if route.pipeline_stage in {"tile_suppression", "ground_context", "infrastructure_context", "recurrence"}:
            assert signal_group_id in configured


def test_weights_must_sum_to_one():
    payload = copy.deepcopy(load_config_defaults().payload)
    payload["threshold_groups"]["tile_suppression"]["signal_groups"]["seam_anomaly_detection"]["weights"][
        "hard_boundary_score"
    ] = 0.99

    with pytest.raises(ConfigDefaultsError, match="weights must sum to 1.0"):
        ConfigDefaults(payload).validate(registry=load_allowed_enum_registry())


def test_review_thresholds_must_be_monotonic():
    payload = copy.deepcopy(load_config_defaults().payload)
    payload["threshold_groups"]["ground_context"]["signal_groups"]["vehicle_cluster_signature"][
        "review_thresholds"
    ]["high_priority_at"] = 0.2

    with pytest.raises(ConfigDefaultsError, match="monotonically increasing"):
        ConfigDefaults(payload).validate(registry=load_allowed_enum_registry())


def test_unknown_configured_signal_group_is_rejected():
    payload = copy.deepcopy(load_config_defaults().payload)
    payload["threshold_groups"]["ground_context"]["signal_groups"]["not_a_real_signal_group"] = copy.deepcopy(
        payload["threshold_groups"]["ground_context"]["signal_groups"]["pool_signature"]
    )

    with pytest.raises(ConfigDefaultsError, match="not allowed by enum registry"):
        ConfigDefaults(payload).validate(registry=load_allowed_enum_registry())


def test_missing_guardrail_is_rejected():
    payload = copy.deepcopy(load_config_defaults().payload)
    del payload["threshold_groups"]["recurrence"]["signal_groups"]["poi_recurrence"]["defaults"][
        "interpretation_guardrail"
    ]

    with pytest.raises(ConfigDefaultsError, match="must include interpretation_guardrail"):
        ConfigDefaults(payload).validate(registry=load_allowed_enum_registry())


def test_suppression_multipliers_must_stay_in_range():
    payload = copy.deepcopy(load_config_defaults().payload)
    payload["threshold_groups"]["ground_context"]["signal_groups"]["land_clearing_signature"][
        "suppression_multipliers"
    ]["tile_artifact"] = 1.5

    with pytest.raises(ConfigDefaultsError, match="must be between 0.0 and 1.0"):
        ConfigDefaults(payload).validate(registry=load_allowed_enum_registry())
