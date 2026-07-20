from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeType(str, Enum):
    NEW_FEATURE = "NEW_FEATURE"
    REMOVED_FEATURE = "REMOVED_FEATURE"
    EXPANSION = "EXPANSION"
    CONTRACTION = "CONTRACTION"
    SHAPE_CHANGE = "SHAPE_CHANGE"
    SURFACE_COVER_CHANGE = "SURFACE_COVER_CHANGE"
    WATER_EXTENT_CHANGE = "WATER_EXTENT_CHANGE"
    ACCESS_CHANGE = "ACCESS_CHANGE"


class TemporalClass(str, Enum):
    STABLE = "STABLE"
    PROBABLE_CHANGE = "PROBABLE_CHANGE"
    CONFIRMED_VISIBLE_CHANGE = "CONFIRMED_VISIBLE_CHANGE"
    ARTIFACT_DRIVEN_CHANGE = "ARTIFACT_DRIVEN_CHANGE"
    INSUFFICIENT_EPOCH_ALIGNMENT = "INSUFFICIENT_EPOCH_ALIGNMENT"


class EvidenceLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    LINEAR_CORRIDOR = "LINEAR_CORRIDOR"
    WATER_FEATURE = "WATER_FEATURE"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_EPOCH_CHANGE_ONLY = "VISIBLE_EPOCH_CHANGE_ONLY"
ORIGINAL_EPOCH_RECORD_IMMUTABILITY = "ORIGINAL_EPOCH_RECORD_IMMUTABILITY"
SEPARATE_BEFORE_AFTER_PROVENANCE = "SEPARATE_BEFORE_AFTER_PROVENANCE"
NO_CAUSAL_INFERENCE = "NO_CAUSAL_INFERENCE"


@dataclass(frozen=True)
class EpochRecord:
    record_id: str
    epoch_id: str
    capture_time: str
    classification: str
    detector_score: float
    geometry_id: str
    map_scale: float
    view_angle: float
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemporalObservation:
    comparison_id: str
    before: EpochRecord
    after: EpochRecord
    change_signals: dict[ChangeType | str, float]
    links: dict[EvidenceLink | str, bool] = field(default_factory=dict)
    spatial_overlap: float = 1.0
    registration_quality: float = 1.0
    scale_compatibility: float = 1.0
    view_angle_compatibility: float = 1.0
    artifact_confidence: float = 0.0
    contradiction_confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class TemporalScore:
    comparison_id: str
    classification: str
    change_score: float
    alignment_score: float
    artifact_confidence: float
    contradiction_confidence: float
    adjusted_change_score: float
    change_types: tuple[str, ...]
    review_required: bool
    review_reasons: tuple[str, ...]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _normalized_changes(observation: TemporalObservation) -> dict[str, float]:
    allowed = {item.value for item in ChangeType}
    return {
        _name(key): clamp01(value)
        for key, value in observation.change_signals.items()
        if _name(key) in allowed
    }


def score_temporal_change(observation: TemporalObservation) -> TemporalScore:
    changes = _normalized_changes(observation)
    change_score = round(max(changes.values(), default=0.0), 4)
    alignment = round(
        (
            clamp01(observation.spatial_overlap)
            + clamp01(observation.registration_quality)
            + clamp01(observation.scale_compatibility)
            + clamp01(observation.view_angle_compatibility)
        )
        / 4.0,
        4,
    )
    artifact = round(clamp01(observation.artifact_confidence), 4)
    contradiction = round(clamp01(observation.contradiction_confidence), 4)
    adjusted = round(clamp01(change_score * alignment * (1.0 - 0.6 * artifact) * (1.0 - 0.3 * contradiction)), 4)

    if alignment < 0.6:
        classification = TemporalClass.INSUFFICIENT_EPOCH_ALIGNMENT
    elif artifact >= 0.7 and change_score >= 0.35:
        classification = TemporalClass.ARTIFACT_DRIVEN_CHANGE
    elif adjusted >= 0.7:
        classification = TemporalClass.CONFIRMED_VISIBLE_CHANGE
    elif adjusted >= 0.35:
        classification = TemporalClass.PROBABLE_CHANGE
    else:
        classification = TemporalClass.STABLE

    reasons: list[str] = []
    if alignment < 0.6:
        reasons.append("LOW_EPOCH_ALIGNMENT")
    if artifact >= 0.7:
        reasons.append("HIGH_ARTIFACT_CONFIDENCE")
    if contradiction >= 0.7:
        reasons.append("HIGH_CONTRADICTION_CONFIDENCE")
    if not observation.before.provenance:
        reasons.append("MISSING_BEFORE_PROVENANCE")
    if not observation.after.provenance:
        reasons.append("MISSING_AFTER_PROVENANCE")

    return TemporalScore(
        comparison_id=observation.comparison_id,
        classification=classification.value,
        change_score=change_score,
        alignment_score=alignment,
        artifact_confidence=artifact,
        contradiction_confidence=contradiction,
        adjusted_change_score=adjusted,
        change_types=tuple(sorted(name for name, value in changes.items() if value > 0.0)),
        review_required=classification in {
            TemporalClass.ARTIFACT_DRIVEN_CHANGE,
            TemporalClass.INSUFFICIENT_EPOCH_ALIGNMENT,
        } or bool(reasons),
        review_reasons=tuple(sorted(set(reasons))),
    )


def temporal_change_schema() -> dict[str, Any]:
    return {
        "detector": "SATIM_TEMPORAL_SURFACE_CHANGE_DETECTOR_v1",
        "change_types": [item.value for item in ChangeType],
        "classes": [item.value for item in TemporalClass],
        "links": [item.value for item in EvidenceLink],
        "guardrails": [
            VISIBLE_EPOCH_CHANGE_ONLY,
            ORIGINAL_EPOCH_RECORD_IMMUTABILITY,
            SEPARATE_BEFORE_AFTER_PROVENANCE,
            NO_CAUSAL_INFERENCE,
        ],
        "outputs": [
            "SATIM_TEMPORAL_CHANGE_LEDGER",
            "DETECTOR_CONFIDENCE_PATCH",
            "HUMAN_REVIEW_QUEUE",
        ],
        "prohibited_outputs": [
            "CAUSAL_INFERENCE",
            "OWNERSHIP_INFERENCE",
            "PURPOSE_INFERENCE",
            "SOURCE_RECORD_MUTATION",
        ],
    }


def _epoch_row(record: EpochRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "epoch_id": record.epoch_id,
        "capture_time": record.capture_time,
        "classification": record.classification,
        "detector_score": clamp01(record.detector_score),
        "geometry_id": record.geometry_id,
        "map_scale": record.map_scale,
        "view_angle": record.view_angle,
        "provenance": dict(record.provenance),
    }


def build_temporal_change_ledger(observations: list[TemporalObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_temporal_change(observation)
        rows.append({
            "comparison_id": observation.comparison_id,
            "classification": score.classification,
            "change_score": score.change_score,
            "alignment_score": score.alignment_score,
            "artifact_confidence": score.artifact_confidence,
            "contradiction_confidence": score.contradiction_confidence,
            "adjusted_change_score": score.adjusted_change_score,
            "change_types": list(score.change_types),
            "before": _epoch_row(observation.before),
            "after": _epoch_row(observation.after),
            "linked_evidence": sorted(_name(key) for key, value in observation.links.items() if value),
            "review_required": score.review_required,
            "review_reasons": list(score.review_reasons),
            "guardrails": [VISIBLE_EPOCH_CHANGE_ONLY, ORIGINAL_EPOCH_RECORD_IMMUTABILITY, SEPARATE_BEFORE_AFTER_PROVENANCE, NO_CAUSAL_INFERENCE],
            "notes": observation.notes,
        })
    return rows


def build_detector_confidence_patch(observations: list[TemporalObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_temporal_change(observation)
        for role, record in (("BEFORE", observation.before), ("AFTER", observation.after)):
            rows.append({
                "comparison_id": observation.comparison_id,
                "epoch_role": role,
                "record_id": record.record_id,
                "original_classification": record.classification,
                "original_score": clamp01(record.detector_score),
                "temporal_change_confidence": score.adjusted_change_score,
                "patch_status": "DETECTOR_CONFIDENCE_PATCH",
                "mutation_rule": "original epoch record retained; emit temporal context patch only",
                "guardrail": VISIBLE_EPOCH_CHANGE_ONLY,
            })
    return rows


def build_human_review_queue(observations: list[TemporalObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_temporal_change(observation)
        if not score.review_required:
            continue
        priority = "HIGH" if score.classification == TemporalClass.INSUFFICIENT_EPOCH_ALIGNMENT.value else "MEDIUM"
        rows.append({
            "comparison_id": observation.comparison_id,
            "classification": score.classification,
            "priority": priority,
            "review_reasons": list(score.review_reasons),
            "change_types": list(score.change_types),
            "guardrail": NO_CAUSAL_INFERENCE,
        })
    return rows
