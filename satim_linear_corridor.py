from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CorridorSignal(str, Enum):
    VEGETATION_BREAK = "VEGETATION_BREAK"
    UNPAVED_LINEAR_CLEARING = "UNPAVED_LINEAR_CLEARING"
    UTILITY_EASEMENT = "UTILITY_EASEMENT"
    SERVICE_TRACK = "SERVICE_TRACK"
    DRAINAGE_CORRIDOR = "DRAINAGE_CORRIDOR"
    FENCE_OR_BOUNDARY_STRIP = "FENCE_OR_BOUNDARY_STRIP"
    CONTINUITY = "CONTINUITY"
    LINEARITY = "LINEARITY"
    WIDTH_CONSISTENCY = "WIDTH_CONSISTENCY"
    EDGE_DEFINITION = "EDGE_DEFINITION"
    VEGETATION_CONTRAST = "VEGETATION_CONTRAST"
    SURFACE_CONTRAST = "SURFACE_CONTRAST"
    JUNCTION_OR_TERMINUS_EVIDENCE = "JUNCTION_OR_TERMINUS_EVIDENCE"
    VISIBLE_ASSET_SUPPORT = "VISIBLE_ASSET_SUPPORT"
    RECURRENCE = "RECURRENCE"


class CorridorClass(str, Enum):
    ACCESS_CORRIDOR = "ACCESS_CORRIDOR"
    UTILITY_CORRIDOR = "UTILITY_CORRIDOR"
    DRAINAGE_FEATURE = "DRAINAGE_FEATURE"
    PROPERTY_BOUNDARY = "PROPERTY_BOUNDARY"
    UNKNOWN_LINEAR_CLEARING = "UNKNOWN_LINEAR_CLEARING"


class CorridorLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_LINEAR_FEATURE_ONLY = "VISIBLE_LINEAR_FEATURE_ONLY"
NON_DESTRUCTIVE_ARTIFACT_FILTER = "ARTIFACT_CONFIDENCE_PATCH_NON_DESTRUCTIVE"

SIGNAL_WEIGHTS: dict[CorridorSignal, float] = {
    CorridorSignal.VEGETATION_BREAK: 0.08,
    CorridorSignal.UNPAVED_LINEAR_CLEARING: 0.08,
    CorridorSignal.UTILITY_EASEMENT: 0.06,
    CorridorSignal.SERVICE_TRACK: 0.06,
    CorridorSignal.DRAINAGE_CORRIDOR: 0.06,
    CorridorSignal.FENCE_OR_BOUNDARY_STRIP: 0.05,
    CorridorSignal.CONTINUITY: 0.12,
    CorridorSignal.LINEARITY: 0.12,
    CorridorSignal.WIDTH_CONSISTENCY: 0.08,
    CorridorSignal.EDGE_DEFINITION: 0.06,
    CorridorSignal.VEGETATION_CONTRAST: 0.05,
    CorridorSignal.SURFACE_CONTRAST: 0.05,
    CorridorSignal.JUNCTION_OR_TERMINUS_EVIDENCE: 0.06,
    CorridorSignal.VISIBLE_ASSET_SUPPORT: 0.05,
    CorridorSignal.RECURRENCE: 0.06,
}

LINK_WEIGHTS: dict[CorridorLink, float] = {
    CorridorLink.PATCHWORK_POI: 0.03,
    CorridorLink.ROAD_END_NODE: 0.05,
    CorridorLink.CUT_FILL_FEATURE: 0.04,
    CorridorLink.REPEAT_GRIDID: 0.05,
}

SIGNAL_DEFINITIONS: dict[str, str] = {
    "VEGETATION_BREAK": "Continuous or segmented break in surrounding vegetation.",
    "UNPAVED_LINEAR_CLEARING": "Narrow cleared strip without confirmed paving.",
    "UTILITY_EASEMENT": "Visually maintained corridor consistent with utility access.",
    "SERVICE_TRACK": "Narrow visible track forming a surface access route.",
    "DRAINAGE_CORRIDOR": "Linear surface feature consistent with visible drainage.",
    "FENCE_OR_BOUNDARY_STRIP": "Linear strip consistent with a visible fence line or field boundary.",
    "CONTINUITY": "Degree to which the feature persists along its visible path.",
    "LINEARITY": "Degree to which the feature follows a coherent linear geometry.",
    "WIDTH_CONSISTENCY": "Stability of apparent corridor width.",
    "EDGE_DEFINITION": "Visibility and consistency of corridor edges.",
    "VEGETATION_CONTRAST": "Contrast between corridor vegetation and surroundings.",
    "SURFACE_CONTRAST": "Contrast between corridor surface and surroundings.",
    "JUNCTION_OR_TERMINUS_EVIDENCE": "Visible junction, node, or terminus support.",
    "VISIBLE_ASSET_SUPPORT": "Visible poles, culverts, fencing, wheel paths, or related assets.",
    "RECURRENCE": "Repeated observation in imagery or the same GridID.",
}


@dataclass(frozen=True)
class CorridorObservation:
    corridor_id: str
    grid_id: str
    source_id: str
    timestamp_local: str = ""
    signals: dict[CorridorSignal | str, float] = field(default_factory=dict)
    classes: tuple[CorridorClass | str, ...] = ()
    links: dict[CorridorLink | str, bool] = field(default_factory=dict)
    patchwork_poi_id: str = ""
    road_end_node_id: str = ""
    cut_fill_feature_id: str = ""
    repeat_grid_id: str = ""
    artifact_confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class CorridorScore:
    corridor_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    classes: tuple[str, ...]
    original_corridor_score: float
    linkage_score: float
    pre_filter_score: float
    artifact_confidence: float
    adjusted_corridor_score: float
    confidence_band: str
    signals: dict[str, float]
    signal_contributions: dict[str, float]
    links: dict[str, bool]
    linked_evidence: tuple[str, ...]
    patchwork_poi_id: str
    road_end_node_id: str
    cut_fill_feature_id: str
    repeat_grid_id: str
    guardrail: str
    artifact_filter_status: str
    notes: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _as_signal(value: CorridorSignal | str) -> CorridorSignal | None:
    try:
        return value if isinstance(value, CorridorSignal) else CorridorSignal(str(value))
    except ValueError:
        return None


def _as_link(value: CorridorLink | str) -> CorridorLink | None:
    try:
        return value if isinstance(value, CorridorLink) else CorridorLink(str(value))
    except ValueError:
        return None


def confidence_band(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def recommended_class(signals: dict[str, float]) -> CorridorClass:
    if signals.get("DRAINAGE_CORRIDOR", 0.0) >= 0.6:
        return CorridorClass.DRAINAGE_FEATURE
    if signals.get("UTILITY_EASEMENT", 0.0) >= 0.6 and signals.get("VISIBLE_ASSET_SUPPORT", 0.0) >= 0.4:
        return CorridorClass.UTILITY_CORRIDOR
    if signals.get("FENCE_OR_BOUNDARY_STRIP", 0.0) >= 0.6:
        return CorridorClass.PROPERTY_BOUNDARY
    if max(signals.get("SERVICE_TRACK", 0.0), signals.get("UNPAVED_LINEAR_CLEARING", 0.0)) >= 0.6:
        return CorridorClass.ACCESS_CORRIDOR
    return CorridorClass.UNKNOWN_LINEAR_CLEARING


def score_corridor_signals(signals: dict[CorridorSignal | str, float]) -> tuple[float, dict[str, float], dict[str, float]]:
    normalized: dict[str, float] = {}
    contributions: dict[str, float] = {}
    total = 0.0
    for raw_signal, raw_value in signals.items():
        signal = _as_signal(raw_signal)
        if signal is None:
            continue
        value = clamp01(float(raw_value))
        normalized[signal.value] = value
        contribution = round(SIGNAL_WEIGHTS[signal] * value, 4)
        contributions[signal.value] = contribution
        total += contribution
    return round(clamp01(total), 4), normalized, contributions


def score_links(links: dict[CorridorLink | str, bool]) -> tuple[float, dict[str, bool], tuple[str, ...]]:
    normalized: dict[str, bool] = {}
    evidence: list[str] = []
    total = 0.0
    for raw_link, raw_present in links.items():
        link = _as_link(raw_link)
        if link is None:
            continue
        present = bool(raw_present)
        normalized[link.value] = present
        if present:
            evidence.append(link.value)
            total += LINK_WEIGHTS[link]
    return round(clamp01(total), 4), normalized, tuple(sorted(evidence))


def apply_artifact_patch(score: float, artifact_confidence: float) -> float:
    return round(clamp01(score * (1.0 - 0.5 * clamp01(artifact_confidence))), 4)


def score_corridor_observation(observation: CorridorObservation) -> CorridorScore:
    original, normalized_signals, contributions = score_corridor_signals(observation.signals)
    linkage, normalized_links, linked = score_links(observation.links)
    pre_filter = round(clamp01(original + linkage), 4)
    artifact = clamp01(float(observation.artifact_confidence))
    adjusted = apply_artifact_patch(pre_filter, artifact)
    classes = tuple(_enum_name(value) for value in observation.classes)
    if not classes:
        classes = (recommended_class(normalized_signals).value,)
    return CorridorScore(
        corridor_id=observation.corridor_id,
        grid_id=observation.grid_id,
        source_id=observation.source_id,
        timestamp_local=observation.timestamp_local,
        classes=classes,
        original_corridor_score=original,
        linkage_score=linkage,
        pre_filter_score=pre_filter,
        artifact_confidence=artifact,
        adjusted_corridor_score=adjusted,
        confidence_band=confidence_band(adjusted),
        signals=normalized_signals,
        signal_contributions=contributions,
        links=normalized_links,
        linked_evidence=linked,
        patchwork_poi_id=observation.patchwork_poi_id,
        road_end_node_id=observation.road_end_node_id,
        cut_fill_feature_id=observation.cut_fill_feature_id,
        repeat_grid_id=observation.repeat_grid_id,
        guardrail=VISIBLE_LINEAR_FEATURE_ONLY,
        artifact_filter_status=NON_DESTRUCTIVE_ARTIFACT_FILTER,
        notes=observation.notes,
    )


def build_linear_corridor_ledger(observations: list[CorridorObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_corridor_observation(observation)
        rows.append({
            "corridor_id": score.corridor_id,
            "grid_id": score.grid_id,
            "source_id": score.source_id,
            "timestamp_local": score.timestamp_local,
            "classes": list(score.classes),
            "original_corridor_score": score.original_corridor_score,
            "linkage_score": score.linkage_score,
            "pre_filter_score": score.pre_filter_score,
            "artifact_confidence": score.artifact_confidence,
            "adjusted_corridor_score": score.adjusted_corridor_score,
            "confidence_band": score.confidence_band,
            "signals": score.signals,
            "signal_contributions": score.signal_contributions,
            "links": score.links,
            "linked_evidence": list(score.linked_evidence),
            "patchwork_poi_id": score.patchwork_poi_id,
            "road_end_node_id": score.road_end_node_id,
            "cut_fill_feature_id": score.cut_fill_feature_id,
            "repeat_grid_id": score.repeat_grid_id,
            "guardrail": score.guardrail,
            "artifact_filter_status": score.artifact_filter_status,
            "notes": score.notes,
        })
    return rows


def build_p_route_confidence_patch(observations: list[CorridorObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_corridor_observation(observation)
        rows.append({
            "corridor_id": score.corridor_id,
            "grid_id": score.grid_id,
            "source_id": score.source_id,
            "original_corridor_score": score.original_corridor_score,
            "linkage_score": score.linkage_score,
            "pre_filter_score": score.pre_filter_score,
            "artifact_confidence": score.artifact_confidence,
            "adjusted_corridor_score": score.adjusted_corridor_score,
            "linked_evidence": list(score.linked_evidence),
            "guardrail": score.guardrail,
            "patch_status": "P_ROUTE_CONFIDENCE_PATCH",
            "mutation_rule": "corridor candidate retained; artifact adjustment is advisory only",
            "provenance_rule": "original, linkage, artifact, and adjusted scores remain separable",
        })
    return rows


def linear_corridor_schema() -> dict[str, Any]:
    return {
        "detector": "SATIM_LINEAR_CLEARING_CORRIDOR_DETECTOR_v1",
        "guardrail": VISIBLE_LINEAR_FEATURE_ONLY,
        "artifact_filter": NON_DESTRUCTIVE_ARTIFACT_FILTER,
        "signals": SIGNAL_DEFINITIONS,
        "classes": [value.value for value in CorridorClass],
        "links": [value.value for value in CorridorLink],
        "signal_weights": {signal.value: weight for signal, weight in SIGNAL_WEIGHTS.items()},
        "link_weights": {link.value: weight for link, weight in LINK_WEIGHTS.items()},
        "confidence_bands": {"LOW": "<0.40", "MEDIUM": "0.40-0.69", "HIGH": ">=0.70"},
        "inference_limit": "visible surface geometry only; no hidden infrastructure, ownership, or operational-purpose claim",
        "artifact_rule": "artifact confidence may reduce advisory confidence but never deletes the candidate",
    }
