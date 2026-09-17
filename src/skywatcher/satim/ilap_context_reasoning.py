"""Contextual, temporal, provenance, and explainability primitives for ILAP v1.1.

All outputs are review-oriented and fail closed. This module does not infer site
purpose, hidden infrastructure, concealment intent, wrongdoing, ownership, or
mission from visual/spatial observations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from statistics import median
from typing import Iterable, Mapping, Sequence

CANDIDATE_FAMILIES = {
    "ILAP_VISUAL_LAYOUT_CANDIDATE",
    "ILAP_ACCESSIBILITY_CANDIDATE",
    "ILAP_HYDRO_CONTEXT_CANDIDATE",
    "ILAP_INFRASTRUCTURE_CANDIDATE",
    "ILAP_TEMPORAL_CHANGE_CANDIDATE",
    "ILAP_ACTIVITY_ANOMALY_CANDIDATE",
    "ILAP_AIRSPACE_CORRELATION_CANDIDATE",
}

NEGATIVE_OBSERVATION_STATES = {
    "OBSERVED_ABSENT",
    "NOT_VISIBLE_OCCLUDED",
    "NOT_VISIBLE_OUT_OF_FRAME",
    "BELOW_RESOLUTION",
    "NOT_MEASURED",
    "UNKNOWN",
}

SITE_VISIBILITY_STATES = {
    "COMPLETE",
    "MOSTLY_VISIBLE",
    "PARTIALLY_VISIBLE",
    "HEAVILY_OCCLUDED",
    "UNKNOWN_EXTENT",
}

INSTANCE_RELATION_STATES = {
    "SAME_OBJECT",
    "POSSIBLE_SAME_OBJECT",
    "SPLIT",
    "MERGED",
    "MISSING_FROM_VIEW",
    "BELOW_RESOLUTION",
    "UNRESOLVED",
}


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    provider: str | None = None
    imagery_epoch: str | None = None
    lineage_id: str | None = None
    derived_from: str | None = None


@dataclass(frozen=True)
class ComparisonSet:
    comparison_set_id: str
    values: tuple[float, ...]
    selection_rule: str
    geography: str | None = None
    terrain_or_landuse_strata: str | None = None
    provider_constraint: str | None = None
    epoch_constraint: str | None = None
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisibilityAssessment:
    visible_ground_fraction: float | None
    canopy_occlusion_fraction: float | None = None
    shadow_occlusion_fraction: float | None = None
    cloud_occlusion_fraction: float | None = None
    ui_occlusion_fraction: float | None = None
    unknown_occlusion_fraction: float | None = None
    state: str = "UNKNOWN_EXTENT"


@dataclass(frozen=True)
class AnnotationRecord:
    annotation_id: str
    source_frame_id: str
    revision: int
    actor_type: str  # HUMAN | MACHINE
    class_name: str
    coordinate_space: str
    evidence_state: str
    ui_color: str | None = None
    analyst_or_system_id: str | None = None
    notes: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class ExplainabilityPacket:
    why_flagged: tuple[str, ...]
    observed: tuple[str, ...]
    not_observed: tuple[str, ...]
    unknown: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    falsifiers_remaining: tuple[str, ...]
    next_data_needed: tuple[str, ...]
    comparison_set_id: str | None
    source_lineage: tuple[str, ...]
    candidate_families: tuple[str, ...] = field(default_factory=tuple)


def _finite_fraction(value: float | None) -> bool:
    return value is not None and isfinite(float(value)) and 0.0 <= float(value) <= 1.0


def assess_visibility(
    visible_ground_fraction: float | None,
    *,
    canopy: float | None = None,
    shadow: float | None = None,
    cloud: float | None = None,
    ui: float | None = None,
    unknown: float | None = None,
) -> VisibilityAssessment:
    """Return a descriptive visibility assessment without invented thresholds.

    Until visibility cutoffs are calibrated, a measured fraction is preserved but
    the categorical state remains UNKNOWN_EXTENT.
    """
    vals = [visible_ground_fraction, canopy, shadow, cloud, ui, unknown]
    for value in vals:
        if value is not None and not _finite_fraction(value):
            raise ValueError("visibility fractions must be within [0,1] or None")
    return VisibilityAssessment(
        visible_ground_fraction=visible_ground_fraction,
        canopy_occlusion_fraction=canopy,
        shadow_occlusion_fraction=shadow,
        cloud_occlusion_fraction=cloud,
        ui_occlusion_fraction=ui,
        unknown_occlusion_fraction=unknown,
        state="UNKNOWN_EXTENT",
    )


def contextual_percentile(observed: float | None, comparison: ComparisonSet | None) -> dict[str, object]:
    """Return a descriptive percentile only when a frozen comparison set exists."""
    if observed is None:
        return {"state": "ABSTAIN_INSUFFICIENT_EVIDENCE", "percentile": None, "comparison_n": 0}
    if comparison is None or not comparison.values:
        return {"state": "ABSTAIN_INSUFFICIENT_EVIDENCE", "percentile": None, "comparison_n": 0}
    if not isfinite(float(observed)):
        raise ValueError("observed value must be finite")
    values = [float(v) for v in comparison.values if isfinite(float(v))]
    if not values:
        return {"state": "ABSTAIN_INSUFFICIENT_EVIDENCE", "percentile": None, "comparison_n": 0}
    le = sum(1 for v in values if v <= float(observed))
    percentile = 100.0 * le / len(values)
    return {
        "state": "DESCRIPTIVE_BASELINE_ONLY",
        "percentile": percentile,
        "comparison_n": len(values),
        "comparison_median": median(values),
        "comparison_set_id": comparison.comparison_set_id,
    }


def independent_source_count(sources: Iterable[SourceRef]) -> int:
    """Count independent lineages, not screenshots or derived copies."""
    lineage_keys: set[str] = set()
    for source in sources:
        if source.derived_from:
            continue
        key = source.lineage_id or f"provider:{source.provider or 'UNKNOWN'}"
        lineage_keys.add(key)
    return len(lineage_keys)


def validate_negative_observation_state(state: str) -> str:
    if state not in NEGATIVE_OBSERVATION_STATES:
        raise ValueError(f"unsupported negative-observation state: {state}")
    return state


def validate_instance_relation_state(state: str) -> str:
    if state not in INSTANCE_RELATION_STATES:
        raise ValueError(f"unsupported instance relation state: {state}")
    return state


def validate_annotation(record: AnnotationRecord) -> AnnotationRecord:
    if record.actor_type not in {"HUMAN", "MACHINE"}:
        raise ValueError("actor_type must be HUMAN or MACHINE")
    if record.revision < 1:
        raise ValueError("annotation revision must be >=1")
    if not record.annotation_id or not record.source_frame_id or not record.class_name:
        raise ValueError("annotation id, source frame id, and class are required")
    return record


def normalize_candidate_families(families: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for family in families:
        if family not in CANDIDATE_FAMILIES:
            raise ValueError(f"unsupported ILAP candidate family: {family}")
        if family not in out:
            out.append(family)
    return tuple(out)


def build_explainability_packet(
    *,
    why_flagged: Sequence[str],
    observed: Sequence[str],
    not_observed: Sequence[str],
    unknown: Sequence[str],
    supporting_evidence: Sequence[str],
    contradicting_evidence: Sequence[str],
    falsifiers_remaining: Sequence[str],
    next_data_needed: Sequence[str],
    comparison_set_id: str | None,
    sources: Sequence[SourceRef],
    candidate_families: Sequence[str],
) -> ExplainabilityPacket:
    families = normalize_candidate_families(candidate_families)
    lineage = tuple(sorted({s.lineage_id or s.source_id for s in sources}))
    return ExplainabilityPacket(
        why_flagged=tuple(why_flagged),
        observed=tuple(observed),
        not_observed=tuple(not_observed),
        unknown=tuple(unknown),
        supporting_evidence=tuple(supporting_evidence),
        contradicting_evidence=tuple(contradicting_evidence),
        falsifiers_remaining=tuple(falsifiers_remaining),
        next_data_needed=tuple(next_data_needed),
        comparison_set_id=comparison_set_id,
        source_lineage=lineage,
        candidate_families=families,
    )
