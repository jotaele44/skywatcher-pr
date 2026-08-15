from __future__ import annotations

from skywatcher.satim.infrastructure_reasoning import (
    InfrastructureObservation,
    assess_infrastructure,
)
from skywatcher.satim.visual_reasoning_runtime import ParameterSet


def _params() -> ParameterSet:
    return ParameterSet(
        {
            "INFRA.CLASS_PROMOTION_MIN": 0.7,
            "INFRA.CLASS_CONFLICT_MARGIN": 0.1,
        }
    )


def test_supported_class_without_subtype_stays_hierarchical() -> None:
    result = assess_infrastructure(
        InfrastructureObservation("transport", 0.9, {}),
        _params(),
    )
    assert result.state == "INFRASTRUCTURE_CLASS_ONLY"
    assert result.metadata["infrastructure_class"] == "transport"
    assert "RC_INFRA_SUBTYPE_UNRESOLVED" in result.reason_codes


def test_tied_subtypes_do_not_use_deterministic_order_as_evidence() -> None:
    result = assess_infrastructure(
        InfrastructureObservation(
            "utility",
            0.9,
            {"tank": 0.82, "tower": 0.80},
        ),
        _params(),
    )
    assert result.state == "INFRASTRUCTURE_CLASS_ONLY"
    assert result.metadata["top_subtype_candidate"] == "tank"
    assert result.metadata["runner_up_subtype_score"] == 0.80


def test_clear_subtype_support_does_not_claim_identity() -> None:
    result = assess_infrastructure(
        InfrastructureObservation(
            "utility",
            0.9,
            {"tank": 0.9, "tower": 0.4},
        ),
        _params(),
    )
    assert result.state == "INFRASTRUCTURE_SUBTYPE_SUPPORTED"
    assert result.metadata["supported_subtype"] == "tank"
    assert result.metadata["identity_binding"] is False


def test_hard_falsifier_wins() -> None:
    result = assess_infrastructure(
        InfrastructureObservation(
            "utility",
            0.95,
            {"tank": 0.95},
            hard_falsifier=True,
        ),
        _params(),
    )
    assert result.state == "REJECTED"
    assert result.reason_codes == ("RC_HARD_FALSIFIER",)
