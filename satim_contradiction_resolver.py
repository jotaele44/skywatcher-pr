from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConflictType(str, Enum):
    CLASS_CONFLICT = "CLASS_CONFLICT"
    GEOMETRY_CONFLICT = "GEOMETRY_CONFLICT"
    TEMPORAL_CONFLICT = "TEMPORAL_CONFLICT"
    ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"
    LINKAGE_CONFLICT = "LINKAGE_CONFLICT"
    PROVENANCE_CONFLICT = "PROVENANCE_CONFLICT"


class ReconciliationClass(str, Enum):
    CONSISTENT = "CONSISTENT"
    SOFT_CONTRADICTION = "SOFT_CONTRADICTION"
    HARD_CONTRADICTION = "HARD_CONTRADICTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DetectorType(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    LINEAR_CORRIDOR = "LINEAR_CORRIDOR"
    WATER_FEATURE = "WATER_FEATURE"
    ARTIFACT_CONFIDENCE_PATCH = "ARTIFACT_CONFIDENCE_PATCH"


EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS = (
    "EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS"
)
ORIGINAL_OUTPUT_IMMUTABILITY = "ORIGINAL_OUTPUT_IMMUTABILITY"


@dataclass(frozen=True)
class DetectorEvidence:
    detector: DetectorType | str
    record_id: str
    classification: str
    score: float
    geometry_id: str = ""
    timestamp_local: str = ""
    links: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    artifact_confidence: float = 0.0


@dataclass(frozen=True)
class ContradictionObservation:
    reconciliation_id: str
    evidence: tuple[DetectorEvidence, ...]
    conflict_strengths: dict[ConflictType | str, float] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class ReconciliationScore:
    reconciliation_id: str
    classification: str
    conflict_score: float
    consistency_score: float
    confidence_multiplier: float
    conflict_types: tuple[str, ...]
    review_required: bool
    review_reasons: tuple[str, ...]
    guardrail: str
    immutability_rule: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _normalized_conflicts(observation: ContradictionObservation) -> dict[str, float]:
    allowed = {item.value for item in ConflictType}
    values: dict[str, float] = {}
    for key, value in observation.conflict_strengths.items():
        name = _name(key)
        if name in allowed:
            values[name] = clamp01(value)
    return values


def _evidence_complete(evidence: tuple[DetectorEvidence, ...]) -> bool:
    if len(evidence) < 2:
        return False
    return all(item.record_id and item.classification for item in evidence)


def score_contradiction(observation: ContradictionObservation) -> ReconciliationScore:
    conflicts = _normalized_conflicts(observation)
    conflict_score = round(max(conflicts.values(), default=0.0), 4)
    evidence_complete = _evidence_complete(observation.evidence)

    if not evidence_complete:
        classification = ReconciliationClass.INSUFFICIENT_EVIDENCE
    elif conflict_score >= 0.75:
        classification = ReconciliationClass.HARD_CONTRADICTION
    elif conflict_score >= 0.35:
        classification = ReconciliationClass.SOFT_CONTRADICTION
    else:
        classification = ReconciliationClass.CONSISTENT

    reasons: list[str] = []
    if not evidence_complete:
        reasons.append("INSUFFICIENT_SOURCE_EVIDENCE")
    for name, value in sorted(conflicts.items()):
        if value >= 0.75:
            reasons.append(f"HIGH_{name}")
        elif value >= 0.35:
            reasons.append(f"MATERIAL_{name}")
    if any(not item.provenance for item in observation.evidence):
        reasons.append("MISSING_SOURCE_PROVENANCE")

    consistency_score = round(clamp01(1.0 - conflict_score), 4)
    multiplier = {
        ReconciliationClass.CONSISTENT: 1.0,
        ReconciliationClass.SOFT_CONTRADICTION: 0.8,
        ReconciliationClass.HARD_CONTRADICTION: 0.5,
        ReconciliationClass.INSUFFICIENT_EVIDENCE: 0.65,
    }[classification]

    return ReconciliationScore(
        reconciliation_id=observation.reconciliation_id,
        classification=classification.value,
        conflict_score=conflict_score,
        consistency_score=consistency_score,
        confidence_multiplier=multiplier,
        conflict_types=tuple(sorted(name for name, value in conflicts.items() if value > 0.0)),
        review_required=classification is not ReconciliationClass.CONSISTENT or bool(reasons),
        review_reasons=tuple(sorted(set(reasons))),
        guardrail=EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS,
        immutability_rule=ORIGINAL_OUTPUT_IMMUTABILITY,
    )


def contradiction_resolver_schema() -> dict[str, Any]:
    return {
        "resolver": "SATIM_SURFACE_FEATURE_CONTRADICTION_RESOLVER_v1",
        "guardrail": EVIDENCE_RECONCILIATION_ONLY_NO_FACT_SYNTHESIS,
        "immutability_rule": ORIGINAL_OUTPUT_IMMUTABILITY,
        "conflict_types": [item.value for item in ConflictType],
        "classes": [item.value for item in ReconciliationClass],
        "detectors": [item.value for item in DetectorType],
        "outputs": [
            "SATIM_CONTRADICTION_LEDGER",
            "DETECTOR_CONFIDENCE_PATCH",
            "HUMAN_REVIEW_QUEUE",
        ],
        "prohibited_outputs": [
            "SYNTHESIZED_FACT",
            "SOURCE_RECORD_MUTATION",
            "OWNERSHIP_INFERENCE",
            "PURPOSE_INFERENCE",
            "HIDDEN_INFRASTRUCTURE_INFERENCE",
            "COORDINATION_INFERENCE",
            "COVERT_ACTIVITY_INFERENCE",
        ],
    }


def _evidence_row(item: DetectorEvidence) -> dict[str, Any]:
    return {
        "detector": _name(item.detector),
        "record_id": item.record_id,
        "classification": item.classification,
        "score": clamp01(item.score),
        "geometry_id": item.geometry_id,
        "timestamp_local": item.timestamp_local,
        "links": list(item.links),
        "provenance": dict(item.provenance),
        "artifact_confidence": clamp01(item.artifact_confidence),
    }


def build_contradiction_ledger(
    observations: list[ContradictionObservation],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_contradiction(observation)
        rows.append(
            {
                "reconciliation_id": observation.reconciliation_id,
                "classification": score.classification,
                "conflict_score": score.conflict_score,
                "consistency_score": score.consistency_score,
                "conflict_types": list(score.conflict_types),
                "source_evidence": [_evidence_row(item) for item in observation.evidence],
                "review_required": score.review_required,
                "review_reasons": list(score.review_reasons),
                "guardrail": score.guardrail,
                "immutability_rule": score.immutability_rule,
                "notes": observation.notes,
            }
        )
    return rows


def build_detector_confidence_patch(
    observations: list[ContradictionObservation],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_contradiction(observation)
        for item in observation.evidence:
            original_score = clamp01(item.score)
            adjusted_score = round(clamp01(original_score * score.confidence_multiplier), 4)
            rows.append(
                {
                    "reconciliation_id": observation.reconciliation_id,
                    "detector": _name(item.detector),
                    "record_id": item.record_id,
                    "original_classification": item.classification,
                    "original_score": original_score,
                    "adjusted_score": adjusted_score,
                    "reconciliation_class": score.classification,
                    "patch_status": "DETECTOR_CONFIDENCE_PATCH",
                    "mutation_rule": "source record retained; emit confidence patch only",
                    "guardrail": score.guardrail,
                }
            )
    return rows


def build_human_review_queue(
    observations: list[ContradictionObservation],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_contradiction(observation)
        if not score.review_required:
            continue
        priority = "HIGH" if score.classification == ReconciliationClass.HARD_CONTRADICTION.value else "MEDIUM"
        if score.classification == ReconciliationClass.INSUFFICIENT_EVIDENCE.value:
            priority = "HIGH"
        rows.append(
            {
                "reconciliation_id": observation.reconciliation_id,
                "classification": score.classification,
                "priority": priority,
                "review_reasons": list(score.review_reasons),
                "conflict_types": list(score.conflict_types),
                "guardrail": score.guardrail,
            }
        )
    return rows
