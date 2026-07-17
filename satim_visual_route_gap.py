from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GapClass(str, Enum):
    GEOMETRICALLY_COMPATIBLE = "GEOMETRICALLY_COMPATIBLE"
    PARTIALLY_COMPATIBLE = "PARTIALLY_COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class GapLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    LINEAR_CORRIDOR = "LINEAR_CORRIDOR"
    ARTIFACT_CONFIDENCE_PATCH = "ARTIFACT_CONFIDENCE_PATCH"


PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION = "PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION"
UNKNOWN_GAP_GEOMETRY = "UNKNOWN_GAP_GEOMETRY"


@dataclass(frozen=True)
class TrackPoint:
    timestamp: str
    latitude: float
    longitude: float
    altitude_ft: float | None = None
    speed_kt: float | None = None
    heading_deg: float | None = None


@dataclass(frozen=True)
class GapObservation:
    gap_id: str
    source_id: str
    pre_gap_anchor: TrackPoint | None
    post_gap_anchor: TrackPoint | None
    observed_track_points: tuple[TrackPoint, ...] = ()
    screenshot_segment_id: str = ""
    screenshot_timestamp: str = ""
    screenshot_georeferenced: bool = False
    gap_duration_score: float | None = None
    endpoint_segment_proximity_score: float | None = None
    temporal_alignment_score: float | None = None
    heading_compatibility_score: float | None = None
    altitude_speed_continuity_score: float | None = None
    repeat_gridid_overlap_score: float | None = None
    visual_feature_proximity_score: float | None = None
    artifact_confidence: float = 0.0
    links: dict[GapLink | str, bool] = field(default_factory=dict)
    flight_provenance: dict[str, Any] = field(default_factory=dict)
    visual_provenance: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class GapScore:
    gap_id: str
    classification: str
    raw_compatibility_score: float
    artifact_penalty: float
    missing_data_penalty: float
    final_compatibility_score: float
    review_required: bool
    review_reasons: tuple[str, ...]
    linked_evidence: tuple[str, ...]
    gap_geometry: str
    guardrail: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _normalized_scores(observation: GapObservation) -> dict[str, float | None]:
    fields = {
        "gap_duration": observation.gap_duration_score,
        "endpoint_segment_proximity": observation.endpoint_segment_proximity_score,
        "temporal_alignment": observation.temporal_alignment_score,
        "heading_compatibility": observation.heading_compatibility_score,
        "altitude_speed_continuity": observation.altitude_speed_continuity_score,
        "repeat_gridid_overlap": observation.repeat_gridid_overlap_score,
        "visual_feature_proximity": observation.visual_feature_proximity_score,
    }
    return {key: None if value is None else clamp01(value) for key, value in fields.items()}


SCORE_WEIGHTS: dict[str, float] = {
    "gap_duration": 0.10,
    "endpoint_segment_proximity": 0.25,
    "temporal_alignment": 0.20,
    "heading_compatibility": 0.15,
    "altitude_speed_continuity": 0.10,
    "repeat_gridid_overlap": 0.10,
    "visual_feature_proximity": 0.10,
}


def score_components(observation: GapObservation) -> tuple[float, float, dict[str, float | None]]:
    normalized = _normalized_scores(observation)
    weighted = 0.0
    available_weight = 0.0
    missing_count = 0
    for name, weight in SCORE_WEIGHTS.items():
        value = normalized[name]
        if value is None:
            missing_count += 1
            continue
        weighted += value * weight
        available_weight += weight
    raw = 0.0 if available_weight == 0.0 else weighted / available_weight
    missing_penalty = min(0.35, missing_count * 0.05)
    return round(clamp01(raw), 4), round(missing_penalty, 4), normalized


def _linked_evidence(links: dict[GapLink | str, bool]) -> tuple[str, ...]:
    values: list[str] = []
    for key, present in links.items():
        if not present:
            continue
        name = _enum_name(key)
        if name in {item.value for item in GapLink}:
            values.append(name)
    return tuple(sorted(set(values)))


def _review_reasons(observation: GapObservation, final_score: float, missing_penalty: float) -> tuple[str, ...]:
    reasons: list[str] = []
    if observation.pre_gap_anchor is None:
        reasons.append("MISSING_PRE_GAP_ANCHOR")
    if observation.post_gap_anchor is None:
        reasons.append("MISSING_POST_GAP_ANCHOR")
    if not observation.screenshot_timestamp:
        reasons.append("AMBIGUOUS_SCREENSHOT_TIMESTAMP")
    if not observation.screenshot_georeferenced:
        reasons.append("VISUAL_SEGMENT_NOT_GEOREFERENCED")
    if clamp01(observation.artifact_confidence) >= 0.7:
        reasons.append("HIGH_ARTIFACT_CONFIDENCE")
    if observation.heading_compatibility_score is not None and observation.heading_compatibility_score <= 0.2:
        reasons.append("CONTRADICTORY_HEADING")
    if observation.temporal_alignment_score is not None and observation.temporal_alignment_score <= 0.2:
        reasons.append("CONTRADICTORY_TIMING")
    if missing_penalty >= 0.2:
        reasons.append("MATERIAL_MISSING_DATA")
    if 0.38 <= final_score <= 0.42 or 0.68 <= final_score <= 0.72:
        reasons.append("CLASS_BOUNDARY_TOLERANCE")
    return tuple(sorted(set(reasons)))


def classify(final_score: float, observation: GapObservation) -> GapClass:
    if observation.pre_gap_anchor is None or observation.post_gap_anchor is None:
        return GapClass.INSUFFICIENT_EVIDENCE
    if not observation.screenshot_georeferenced:
        return GapClass.INSUFFICIENT_EVIDENCE
    if final_score >= 0.70:
        return GapClass.GEOMETRICALLY_COMPATIBLE
    if final_score >= 0.40:
        return GapClass.PARTIALLY_COMPATIBLE
    return GapClass.INCOMPATIBLE


def score_gap_observation(observation: GapObservation) -> GapScore:
    raw, missing_penalty, _ = score_components(observation)
    artifact_penalty = round(clamp01(observation.artifact_confidence) * 0.30, 4)
    final_score = round(clamp01(raw - artifact_penalty - missing_penalty), 4)
    reasons = _review_reasons(observation, final_score, missing_penalty)
    classification = classify(final_score, observation)
    return GapScore(
        gap_id=observation.gap_id,
        classification=classification.value,
        raw_compatibility_score=raw,
        artifact_penalty=artifact_penalty,
        missing_data_penalty=missing_penalty,
        final_compatibility_score=final_score,
        review_required=bool(reasons) or classification is GapClass.INSUFFICIENT_EVIDENCE,
        review_reasons=reasons,
        linked_evidence=_linked_evidence(observation.links),
        gap_geometry=UNKNOWN_GAP_GEOMETRY,
        guardrail=PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION,
    )


def _point_to_dict(point: TrackPoint | None) -> dict[str, Any] | None:
    if point is None:
        return None
    return {
        "timestamp": point.timestamp,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "altitude_ft": point.altitude_ft,
        "speed_kt": point.speed_kt,
        "heading_deg": point.heading_deg,
    }


def build_visual_route_gap_ledger(observations: list[GapObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_gap_observation(observation)
        _, _, components = score_components(observation)
        rows.append({
            "gap_id": observation.gap_id,
            "source_id": observation.source_id,
            "classification": score.classification,
            "raw_compatibility_score": score.raw_compatibility_score,
            "artifact_penalty": score.artifact_penalty,
            "missing_data_penalty": score.missing_data_penalty,
            "final_compatibility_score": score.final_compatibility_score,
            "score_components": components,
            "pre_gap_anchor": _point_to_dict(observation.pre_gap_anchor),
            "post_gap_anchor": _point_to_dict(observation.post_gap_anchor),
            "observed_track_points": [_point_to_dict(point) for point in observation.observed_track_points],
            "screenshot_segment_id": observation.screenshot_segment_id,
            "gap_geometry": score.gap_geometry,
            "linked_evidence": list(score.linked_evidence),
            "flight_provenance": dict(observation.flight_provenance),
            "visual_provenance": dict(observation.visual_provenance),
            "review_required": score.review_required,
            "review_reasons": list(score.review_reasons),
            "guardrail": score.guardrail,
            "notes": observation.notes,
        })
    return rows


def build_p_route_confidence_patch(observations: list[GapObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_gap_observation(observation)
        rows.append({
            "gap_id": observation.gap_id,
            "classification": score.classification,
            "final_compatibility_score": score.final_compatibility_score,
            "linked_evidence": list(score.linked_evidence),
            "patch_status": "P_ROUTE_CONFIDENCE_PATCH",
            "mutation_rule": "observed track retained; no gap polyline generated",
            "provenance_rule": "flight and visual provenance remain separate",
            "guardrail": score.guardrail,
        })
    return rows


def build_human_review_queue(observations: list[GapObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_gap_observation(observation)
        if not score.review_required:
            continue
        rows.append({
            "gap_id": observation.gap_id,
            "classification": score.classification,
            "final_compatibility_score": score.final_compatibility_score,
            "review_reasons": list(score.review_reasons),
            "priority": "HIGH" if score.classification == GapClass.INSUFFICIENT_EVIDENCE.value else "NORMAL",
            "guardrail": score.guardrail,
        })
    return rows


def visual_route_gap_schema() -> dict[str, Any]:
    return {
        "joiner": "SATIM_FR24_VISUAL_ROUTE_GAP_JOINER_v1",
        "guardrail": PROXIMITY_ONLY_NO_ROUTE_RECONSTRUCTION,
        "gap_geometry": UNKNOWN_GAP_GEOMETRY,
        "classes": [value.value for value in GapClass],
        "links": [value.value for value in GapLink],
        "score_weights": SCORE_WEIGHTS,
        "outputs": ["SATIM_VISUAL_ROUTE_GAP_LEDGER", "P_ROUTE_CONFIDENCE_PATCH", "HUMAN_REVIEW_QUEUE"],
        "preservation": [
            "OBSERVED_TRACK_POINTS",
            "PRE_GAP_ANCHOR",
            "POST_GAP_ANCHOR",
            "SEPARATE_VISUAL_AND_FLIGHT_EVIDENCE",
        ],
        "prohibited_outputs": ["SYNTHETIC_GAP_POLYLINE", "ASSERTED_ROUTE_TRAVERSAL", "PURPOSE_INFERENCE"],
    }
