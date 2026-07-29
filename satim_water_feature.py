from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WaterSignal(str, Enum):
    PERMANENT_POND = "PERMANENT_POND"
    RETENTION_BASIN = "RETENTION_BASIN"
    DETENTION_BASIN = "DETENTION_BASIN"
    SEASONAL_WATER = "SEASONAL_WATER"
    EXCAVATED_WATER_BODY = "EXCAVATED_WATER_BODY"
    SPILLWAY = "SPILLWAY"
    DRAINAGE_OUTLET = "DRAINAGE_OUTLET"
    BERM = "BERM"
    WATER_SURFACE_VISIBILITY = "WATER_SURFACE_VISIBILITY"
    SHORELINE_CONTINUITY = "SHORELINE_CONTINUITY"
    BASIN_GEOMETRY = "BASIN_GEOMETRY"
    EXCAVATION_EVIDENCE = "EXCAVATION_EVIDENCE"
    BERM_CONTINUITY = "BERM_CONTINUITY"
    INLET_OUTLET_VISIBILITY = "INLET_OUTLET_VISIBILITY"
    SPILLWAY_EVIDENCE = "SPILLWAY_EVIDENCE"
    VEGETATION_MOISTURE_CONTRAST = "VEGETATION_MOISTURE_CONTRAST"
    RECURRENCE = "RECURRENCE"


class WaterClass(str, Enum):
    NATURAL_WATER = "NATURAL_WATER"
    ARTIFICIAL_RETENTION = "ARTIFICIAL_RETENTION"
    AGRICULTURAL_RESERVOIR = "AGRICULTURAL_RESERVOIR"
    QUARRY_WATER = "QUARRY_WATER"
    STORMWATER_FEATURE = "STORMWATER_FEATURE"
    UNKNOWN_WATER = "UNKNOWN_WATER"


class WaterLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"
    LINEAR_CORRIDOR = "LINEAR_CORRIDOR"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_SURFACE_HYDROLOGY_ONLY = "VISIBLE_SURFACE_HYDROLOGY_ONLY"
NON_DESTRUCTIVE_ARTIFACT_FILTER = "ARTIFACT_CONFIDENCE_PATCH_NON_DESTRUCTIVE"


SIGNAL_WEIGHTS: dict[WaterSignal, float] = {
    WaterSignal.PERMANENT_POND: 0.06,
    WaterSignal.RETENTION_BASIN: 0.06,
    WaterSignal.DETENTION_BASIN: 0.05,
    WaterSignal.SEASONAL_WATER: 0.04,
    WaterSignal.EXCAVATED_WATER_BODY: 0.06,
    WaterSignal.SPILLWAY: 0.04,
    WaterSignal.DRAINAGE_OUTLET: 0.04,
    WaterSignal.BERM: 0.04,
    WaterSignal.WATER_SURFACE_VISIBILITY: 0.14,
    WaterSignal.SHORELINE_CONTINUITY: 0.10,
    WaterSignal.BASIN_GEOMETRY: 0.09,
    WaterSignal.EXCAVATION_EVIDENCE: 0.07,
    WaterSignal.BERM_CONTINUITY: 0.06,
    WaterSignal.INLET_OUTLET_VISIBILITY: 0.05,
    WaterSignal.SPILLWAY_EVIDENCE: 0.04,
    WaterSignal.VEGETATION_MOISTURE_CONTRAST: 0.03,
    WaterSignal.RECURRENCE: 0.03,
}

LINK_WEIGHTS: dict[WaterLink, float] = {
    WaterLink.PATCHWORK_POI: 0.02,
    WaterLink.ROAD_END_NODE: 0.03,
    WaterLink.CUT_FILL_FEATURE: 0.04,
    WaterLink.LINEAR_CORRIDOR: 0.03,
    WaterLink.REPEAT_GRIDID: 0.04,
}


@dataclass(frozen=True)
class WaterObservation:
    feature_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    signals: dict[WaterSignal | str, float]
    classes: tuple[WaterClass | str, ...] = ()
    links: dict[WaterLink | str, bool] = field(default_factory=dict)
    patchwork_poi_id: str = ""
    road_end_node_id: str = ""
    cut_fill_feature_id: str = ""
    linear_corridor_id: str = ""
    repeat_grid_id: str = ""
    artifact_confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class WaterScore:
    feature_id: str
    classes: tuple[str, ...]
    original_detector_score: float
    linkage_score: float
    pre_filter_score: float
    artifact_confidence: float
    adjusted_detector_score: float
    confidence_band: str
    review_required: bool
    review_reasons: tuple[str, ...]
    linked_evidence: tuple[str, ...]
    guardrail: str
    artifact_filter_status: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _class_names(values: tuple[WaterClass | str, ...]) -> tuple[str, ...]:
    allowed = {item.value for item in WaterClass}
    names = tuple(sorted({_name(value) for value in values if _name(value) in allowed}))
    return names or (WaterClass.UNKNOWN_WATER.value,)


def _linked_evidence(links: dict[WaterLink | str, bool]) -> tuple[str, ...]:
    allowed = {item.value for item in WaterLink}
    return tuple(sorted({_name(key) for key, present in links.items() if present and _name(key) in allowed}))


def score_water_observation(observation: WaterObservation) -> WaterScore:
    contributions = []
    for signal, weight in SIGNAL_WEIGHTS.items():
        value = observation.signals.get(signal, observation.signals.get(signal.value, 0.0))
        contributions.append(clamp01(value) * weight)
    original = round(clamp01(sum(contributions)), 4)

    linkage = 0.0
    for link, weight in LINK_WEIGHTS.items():
        present = observation.links.get(link, observation.links.get(link.value, False))
        if present:
            linkage += weight
    linkage = round(clamp01(linkage), 4)
    pre_filter = round(clamp01(original + linkage), 4)
    artifact = round(clamp01(observation.artifact_confidence), 4)
    adjusted = round(clamp01(pre_filter * (1.0 - 0.5 * artifact)), 4)

    if adjusted >= 0.75:
        band = "HIGH"
    elif adjusted >= 0.45:
        band = "MEDIUM"
    else:
        band = "LOW"

    reasons: list[str] = []
    if artifact >= 0.7:
        reasons.append("HIGH_ARTIFACT_CONFIDENCE")
    if adjusted < 0.45:
        reasons.append("LOW_ADJUSTED_CONFIDENCE")
    if _class_names(observation.classes) == (WaterClass.UNKNOWN_WATER.value,):
        reasons.append("UNKNOWN_WATER_CLASS")
    if not observation.signals:
        reasons.append("NO_VISIBLE_SIGNAL_VALUES")

    return WaterScore(
        feature_id=observation.feature_id,
        classes=_class_names(observation.classes),
        original_detector_score=original,
        linkage_score=linkage,
        pre_filter_score=pre_filter,
        artifact_confidence=artifact,
        adjusted_detector_score=adjusted,
        confidence_band=band,
        review_required=bool(reasons),
        review_reasons=tuple(sorted(set(reasons))),
        linked_evidence=_linked_evidence(observation.links),
        guardrail=VISIBLE_SURFACE_HYDROLOGY_ONLY,
        artifact_filter_status=NON_DESTRUCTIVE_ARTIFACT_FILTER,
    )


def water_feature_schema() -> dict[str, Any]:
    return {
        "detector": "SATIM_WATER_RETENTION_AND_POND_DETECTOR_v1",
        "guardrail": VISIBLE_SURFACE_HYDROLOGY_ONLY,
        "artifact_filter": NON_DESTRUCTIVE_ARTIFACT_FILTER,
        "signals": [item.value for item in WaterSignal],
        "signal_weights": {item.value: weight for item, weight in SIGNAL_WEIGHTS.items()},
        "classes": [item.value for item in WaterClass],
        "links": [item.value for item in WaterLink],
        "outputs": [
            "SATIM_WATER_FEATURE_LEDGER",
            "HYDROLOGY_CONTEXT_LAYER",
            "P_ROUTE_CONFIDENCE_PATCH",
        ],
        "prohibited_claims": [
            "OWNERSHIP_INFERENCE",
            "SUBSURFACE_SYSTEM_INFERENCE",
            "MISSION_INFERENCE",
            "CONTAMINATION_INFERENCE",
            "COORDINATION_INFERENCE",
            "COVERT_ACTIVITY_INFERENCE",
        ],
    }


def _score_row(observation: WaterObservation, score: WaterScore) -> dict[str, Any]:
    contributions = {
        signal.value: round(
            clamp01(observation.signals.get(signal, observation.signals.get(signal.value, 0.0))) * weight,
            4,
        )
        for signal, weight in SIGNAL_WEIGHTS.items()
    }
    return {
        "feature_id": observation.feature_id,
        "grid_id": observation.grid_id,
        "source_id": observation.source_id,
        "timestamp_local": observation.timestamp_local,
        "classes": list(score.classes),
        "original_detector_score": score.original_detector_score,
        "linkage_score": score.linkage_score,
        "pre_filter_score": score.pre_filter_score,
        "artifact_confidence": score.artifact_confidence,
        "adjusted_detector_score": score.adjusted_detector_score,
        "confidence_band": score.confidence_band,
        "review_required": score.review_required,
        "review_reasons": list(score.review_reasons),
        "linked_evidence": list(score.linked_evidence),
        "signal_contributions": contributions,
        "patchwork_poi_id": observation.patchwork_poi_id,
        "road_end_node_id": observation.road_end_node_id,
        "cut_fill_feature_id": observation.cut_fill_feature_id,
        "linear_corridor_id": observation.linear_corridor_id,
        "repeat_grid_id": observation.repeat_grid_id,
        "guardrail": score.guardrail,
        "artifact_filter_status": score.artifact_filter_status,
        "notes": observation.notes,
    }


def build_water_feature_ledger(observations: list[WaterObservation]) -> list[dict[str, Any]]:
    return [_score_row(observation, score_water_observation(observation)) for observation in observations]


def build_hydrology_context_layer(observations: list[WaterObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_water_observation(observation)
        rows.append({
            "feature_id": observation.feature_id,
            "grid_id": observation.grid_id,
            "classes": list(score.classes),
            "adjusted_detector_score": score.adjusted_detector_score,
            "confidence_band": score.confidence_band,
            "linked_evidence": list(score.linked_evidence),
            "context_rule": "visible hydrology context only; no purpose or ownership inference",
            "guardrail": score.guardrail,
        })
    return rows


def build_p_route_confidence_patch(observations: list[WaterObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        score = score_water_observation(observation)
        rows.append({
            "feature_id": observation.feature_id,
            "original_detector_score": score.original_detector_score,
            "adjusted_detector_score": score.adjusted_detector_score,
            "linked_evidence": list(score.linked_evidence),
            "patch_status": "P_ROUTE_CONFIDENCE_PATCH",
            "mutation_rule": "candidate retained; emit confidence patch only",
            "guardrail": score.guardrail,
        })
    return rows
