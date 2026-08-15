"""Hierarchical infrastructure classification for canonical SATIM visual reasoning.

This layer receives measured class/subtype support from upstream imagery feature
extractors. It does not identify legal owners, facilities, missions, or intent.
When the broad class is supported but subtype evidence is tied or insufficient,
it deliberately returns ``INFRASTRUCTURE_CLASS_ONLY``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .visual_reasoning_runtime import ParameterSet, ReasoningOutcome


@dataclass(frozen=True)
class InfrastructureObservation:
    infrastructure_class: str
    class_support: float | None
    subtype_support: Mapping[str, float]
    hard_falsifier: bool = False


def assess_infrastructure(
    obs: InfrastructureObservation,
    params: ParameterSet,
) -> ReasoningOutcome:
    if obs.class_support is None:
        return ReasoningOutcome(
            "UNRESOLVED",
            reason_codes=("RC_MISSING_NOT_NEGATIVE",),
            metadata={"missing_observation": ("class_support",)},
        )
    required = params.require(
        "INFRA.CLASS_PROMOTION_MIN",
        "INFRA.CLASS_CONFLICT_MARGIN",
    )
    if required is None:
        return ReasoningOutcome(
            "UNRESOLVED",
            reason_codes=("RC_MISSING_NOT_NEGATIVE",),
            metadata={
                "missing_required": (
                    "INFRA.CLASS_PROMOTION_MIN",
                    "INFRA.CLASS_CONFLICT_MARGIN",
                )
            },
        )
    class_min, conflict_margin = required
    if obs.hard_falsifier:
        return ReasoningOutcome(
            "REJECTED",
            reason_codes=("RC_HARD_FALSIFIER",),
        )
    if obs.class_support < class_min:
        return ReasoningOutcome(
            "UNRESOLVED",
            confidence=obs.class_support,
            reason_codes=("RC_MISSING_NOT_NEGATIVE",),
        )

    ordered = sorted(
        ((float(score), name) for name, score in obs.subtype_support.items()),
        key=lambda row: (-row[0], row[1]),
    )
    if not ordered:
        return ReasoningOutcome(
            "INFRASTRUCTURE_CLASS_ONLY",
            confidence=obs.class_support,
            reason_codes=("RC_INFRA_SUBTYPE_UNRESOLVED",),
            metadata={"infrastructure_class": obs.infrastructure_class},
        )

    top_score, top_name = ordered[0]
    runner_score = ordered[1][0] if len(ordered) > 1 else None
    if top_score < class_min or (
        runner_score is not None and top_score - runner_score < conflict_margin
    ):
        return ReasoningOutcome(
            "INFRASTRUCTURE_CLASS_ONLY",
            confidence=obs.class_support,
            reason_codes=("RC_INFRA_SUBTYPE_UNRESOLVED",),
            metadata={
                "infrastructure_class": obs.infrastructure_class,
                "top_subtype_candidate": top_name,
                "top_subtype_score": top_score,
                "runner_up_subtype_score": runner_score,
            },
        )

    return ReasoningOutcome(
        "INFRASTRUCTURE_SUBTYPE_SUPPORTED",
        confidence=min(obs.class_support, top_score),
        metadata={
            "infrastructure_class": obs.infrastructure_class,
            "supported_subtype": top_name,
            "runner_up_subtype_score": runner_score,
            "identity_binding": False,
        },
    )
