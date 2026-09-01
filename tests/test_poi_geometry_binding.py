from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from poi_attribution.geometry_binding import (
    BindingDecision,
    BindingEvidence,
    DiscoverySignal,
    evaluate_geometry_binding,
)

FIXTURE = Path(__file__).parent / "fixtures" / "poi_attribution" / "canovanas_econo_vs_walmart.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "signal",
    [
        DiscoverySignal.NEAREST_ONLY,
        DiscoverySignal.PROXIMITY_ONLY,
        DiscoverySignal.SEARCH_RANK,
        DiscoverySignal.SAME_CATEGORY,
        DiscoverySignal.UNBOUND_MAP_LABEL,
    ],
)
def test_discovery_signals_never_prove_identity(signal: DiscoverySignal) -> None:
    result = evaluate_geometry_binding(
        candidate_name="Nearby candidate",
        target_geometry_id="target-1",
        candidate_geometry_id=None,
        binding_evidence=BindingEvidence.NONE,
        discovery_signals=frozenset({signal}),
    )
    assert result.decision is BindingDecision.UNRESOLVED


def test_canovanas_walmart_false_positive_is_rejected() -> None:
    case = _fixture()
    walmart = next(row for row in case["candidates"] if row["name"] == "Walmart Supercenter")
    result = evaluate_geometry_binding(
        candidate_name=walmart["name"],
        target_geometry_id=case["target_geometry_id"],
        candidate_geometry_id=walmart["candidate_geometry_id"],
        binding_evidence=BindingEvidence(walmart["binding_evidence"]),
        discovery_signals=frozenset(DiscoverySignal(v) for v in walmart["discovery_signals"]),
    )
    assert result.decision is BindingDecision.REJECTED
    assert "distinct-property" in result.reason


def test_canovanas_econo_candidate_binds_to_target() -> None:
    case = _fixture()
    econo = next(row for row in case["candidates"] if row["name"] == "Centro de Distribución Econo")
    result = evaluate_geometry_binding(
        candidate_name=econo["name"],
        target_geometry_id=case["target_geometry_id"],
        candidate_geometry_id=econo["candidate_geometry_id"],
        binding_evidence=BindingEvidence(econo["binding_evidence"]),
        discovery_signals=frozenset(DiscoverySignal(v) for v in econo["discovery_signals"]),
    )
    assert result.decision is BindingDecision.BOUND


def test_geometry_lock_is_required() -> None:
    with pytest.raises(ValueError, match="geometry must be locked"):
        evaluate_geometry_binding(
            candidate_name="Candidate",
            target_geometry_id="",
            candidate_geometry_id=None,
            binding_evidence=BindingEvidence.NONE,
        )


def test_mismatched_candidate_geometry_is_a_falsifier() -> None:
    result = evaluate_geometry_binding(
        candidate_name="Wrong property",
        target_geometry_id="target-1",
        candidate_geometry_id="target-2",
        binding_evidence=BindingEvidence.NONE,
    )
    assert result.decision is BindingDecision.REJECTED


def test_facility_class_cannot_influence_binding_api() -> None:
    parameters = inspect.signature(evaluate_geometry_binding).parameters
    assert "facility_class" not in parameters
