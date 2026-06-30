from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CutFillSignal(str, Enum):
    EXCAVATION_FACE = "EXCAVATION_FACE"
    GRADED_PAD = "GRADED_PAD"
    SPOIL_PILE = "SPOIL_PILE"
    BORROW_PIT = "BORROW_PIT"
    TERRACE_SCARP = "TERRACE_SCARP"
    RETAINING_FILL = "RETAINING_FILL"
    PATCHWORK_POI_LINK = "PATCHWORK_POI_LINK"
    ROAD_END_NODE_LINK = "ROAD_END_NODE_LINK"
    ROUTE_LINKAGE = "ROUTE_LINKAGE"


class CutFillClass(str, Enum):
    QUARRY = "QUARRY"
    LANDFILL = "LANDFILL"
    ROAD_CUT = "ROAD_CUT"
    DRAINAGE_WORK = "DRAINAGE_WORK"
    CONSTRUCTION_PAD = "CONSTRUCTION_PAD"
    UNKNOWN_EARTHWORK = "UNKNOWN_EARTHWORK"


class CutFillLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    FR24_ROUTE_PROXIMITY = "FR24_ROUTE_PROXIMITY"
    ADS_B_GAP = "ADS_B_GAP"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_EARTHWORK_ONLY_STATUS = "VISIBLE_EARTHWORK_ONLY"

SIGNAL_WEIGHTS: dict[CutFillSignal, float] = {
    CutFillSignal.EXCAVATION_FACE: 0.25,
    CutFillSignal.GRADED_PAD: 0.20,
    CutFillSignal.SPOIL_PILE: 0.15,
    CutFillSignal.BORROW_PIT: 0.20,
    CutFillSignal.TERRACE_SCARP: 0.15,
    CutFillSignal.RETAINING_FILL: 0.15,
    CutFillSignal.PATCHWORK_POI_LINK: 0.10,
    CutFillSignal.ROAD_END_NODE_LINK: 0.10,
    CutFillSignal.ROUTE_LINKAGE: 0.30,
}

LINK_WEIGHTS: dict[CutFillLink, float] = {
    CutFillLink.PATCHWORK_POI: 0.10,
    CutFillLink.ROAD_END_NODE: 0.10,
    CutFillLink.FR24_ROUTE_PROXIMITY: 0.10,
    CutFillLink.ADS_B_GAP: 0.10,
    CutFillLink.REPEAT_GRIDID: 0.10,
}

SIGNAL_DEFINITIONS: dict[str, dict[str, str]] = {
    "EXCAVATION_FACE": {
        "definition": "Exposed cut face or active/inactive excavation wall.",
        "visual_cue": "Bright soil/rock face, steep scarp, angular exposed edge.",
    },
    "GRADED_PAD": {
        "definition": "Flattened or compacted prepared surface.",
        "visual_cue": "Leveled pad, smoothed soil, cleared construction apron.",
    },
    "SPOIL_PILE": {
        "definition": "Piled excavated material or fill stockpile.",
        "visual_cue": "Mounded soil/rock, lobe-shaped pile, irregular bright texture.",
    },
    "BORROW_PIT": {
        "definition": "Excavated depression or material extraction pit.",
        "visual_cue": "Bowl/depression, exposed floor, access track into pit.",
    },
    "TERRACE_SCARP": {
        "definition": "Step-like slope cut or bench on hillside.",
        "visual_cue": "Linear/curved bench, break-in-slope, terraced exposed edge.",
    },
    "RETAINING_FILL": {
        "definition": "Built-up embankment, fill edge, or retained surface.",
        "visual_cue": "Raised pad edge, embankment toe, retaining wall or fill boundary.",
    },
}


@dataclass(frozen=True)
class CutFillObservation:
    feature_id: str
    grid_id: str
    source_id: str
    timestamp_local: str = ""
    signals: dict[CutFillSignal | str, float] = field(default_factory=dict)
    classes: tuple[CutFillClass | str, ...] = ()
    links: dict[CutFillLink | str, bool] = field(default_factory=dict)
    patchwork_poi_id: str = ""
    road_end_node_id: str = ""
    notes: str = ""


@dataclass(frozen=True)
class CutFillScore:
    feature_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    classes: tuple[str, ...]
    visible_earthwork_score: float
    linkage_score: float
    combined_score: float
    confidence_band: str
    earthwork_status: str
    visible_earthwork_only_guardrail: bool
    signals: dict[str, float]
    signal_contributions: dict[str, float]
    links: dict[str, bool]
    linked_evidence: tuple[str, ...]
    patchwork_poi_id: str
    road_end_node_id: str
    notes: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _as_signal(value: CutFillSignal | str) -> CutFillSignal | None:
    if isinstance(value, CutFillSignal):
        return value
    try:
        return CutFillSignal(str(value))
    except ValueError:
        return None


def _as_link(value: CutFillLink | str) -> CutFillLink | None:
    if isinstance(value, CutFillLink):
        return value
    try:
        return CutFillLink(str(value))
    except ValueError:
        return None


def confidence_band(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def score_visible_earthwork(signals: dict[CutFillSignal | str, float]) -> tuple[float, dict[str, float]]:
    contributions: dict[str, float] = {}
    total = 0.0
    link_signals = {
        CutFillSignal.PATCHWORK_POI_LINK,
        CutFillSignal.ROAD_END_NODE_LINK,
        CutFillSignal.ROUTE_LINKAGE,
    }
    for raw_signal, raw_presence in signals.items():
        signal = _as_signal(raw_signal)
        if signal is None or signal in link_signals:
            continue
        presence = clamp01(float(raw_presence))
        contribution = round(SIGNAL_WEIGHTS.get(signal, 0.0) * presence, 4)
        contributions[signal.value] = contribution
        total += contribution
    return round(clamp01(total), 4), contributions


def score_links(links: dict[CutFillLink | str, bool]) -> tuple[float, tuple[str, ...]]:
    evidence: list[str] = []
    total = 0.0
    for raw_link, present in links.items():
        link = _as_link(raw_link)
        if link is None or not bool(present):
            continue
        evidence.append(link.value)
        total += LINK_WEIGHTS.get(link, 0.0)
    return round(clamp01(total), 4), tuple(sorted(evidence))


def score_cut_fill_observation(observation: CutFillObservation) -> CutFillScore:
    earthwork_score, contributions = score_visible_earthwork(observation.signals)
    linkage_score, evidence = score_links(observation.links)
    combined = round(clamp01(earthwork_score + linkage_score), 4)
    normalized_signals = {
        _enum_name(k): clamp01(float(v)) for k, v in observation.signals.items()
    }
    normalized_links = {_enum_name(k): bool(v) for k, v in observation.links.items()}
    classes = tuple(_enum_name(c) for c in observation.classes)
    return CutFillScore(
        feature_id=observation.feature_id,
        grid_id=observation.grid_id,
        source_id=observation.source_id,
        timestamp_local=observation.timestamp_local,
        classes=classes,
        visible_earthwork_score=earthwork_score,
        linkage_score=linkage_score,
        combined_score=combined,
        confidence_band=confidence_band(combined),
        earthwork_status=VISIBLE_EARTHWORK_ONLY_STATUS,
        visible_earthwork_only_guardrail=True,
        signals=normalized_signals,
        signal_contributions=contributions,
        links=normalized_links,
        linked_evidence=evidence,
        patchwork_poi_id=observation.patchwork_poi_id,
        road_end_node_id=observation.road_end_node_id,
        notes=observation.notes,
    )


def build_cut_fill_ledger(observations: list[CutFillObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_cut_fill_observation(obs)
        rows.append(
            {
                "feature_id": score.feature_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "classes": list(score.classes),
                "visible_earthwork_score": score.visible_earthwork_score,
                "linkage_score": score.linkage_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "earthwork_status": score.earthwork_status,
                "visible_earthwork_only_guardrail": score.visible_earthwork_only_guardrail,
                "signals": score.signals,
                "signal_contributions": score.signal_contributions,
                "links": score.links,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "road_end_node_id": score.road_end_node_id,
                "notes": score.notes,
            }
        )
    return rows


def build_p_route_confidence_patch(observations: list[CutFillObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_cut_fill_observation(obs)
        rows.append(
            {
                "feature_id": score.feature_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "visible_earthwork_score": score.visible_earthwork_score,
                "linkage_score": score.linkage_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "road_end_node_id": score.road_end_node_id,
                "provenance_rule": "visible_earthwork_score and linkage_score remain separable",
                "guardrail_status": score.earthwork_status,
            }
        )
    return rows


def cut_fill_schema() -> dict[str, Any]:
    return {
        "classifier": "SATIM_CUT_FILL_EXPOSURE_CLASSIFIER_v1",
        "guardrail": VISIBLE_EARTHWORK_ONLY_STATUS,
        "signals": SIGNAL_DEFINITIONS,
        "classes": [klass.value for klass in CutFillClass],
        "links": [link.value for link in CutFillLink],
        "confidence_bands": {"LOW": "<0.40", "MEDIUM": "0.40-0.69", "HIGH": ">=0.70"},
        "signal_weights": {signal.value: weight for signal, weight in SIGNAL_WEIGHTS.items()},
        "link_weights": {link.value: weight for link, weight in LINK_WEIGHTS.items()},
    }
