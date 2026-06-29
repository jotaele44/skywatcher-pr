from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoadEndSignal(str, Enum):
    DEAD_END = "DEAD_END"
    BULB_LOOP = "BULB_LOOP"
    WIDENED_SERVICE_PAD = "WIDENED_SERVICE_PAD"
    PULL_OFF = "PULL_OFF"
    SWITCHBACK_TERMINUS = "SWITCHBACK_TERMINUS"
    PATCHWORK_POI_LINK = "PATCHWORK_POI_LINK"
    ROUTE_LINKAGE = "ROUTE_LINKAGE"


class RoadEndClass(str, Enum):
    ACCESS_NODE = "ACCESS_NODE"
    MAINTENANCE_TURNAROUND = "MAINTENANCE_TURNAROUND"
    STAGING_PAD = "STAGING_PAD"
    PRIVATE_DRIVE_END = "PRIVATE_DRIVE_END"
    UTILITY_SERVICE_END = "UTILITY_SERVICE_END"


class RoadEndLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    FR24_ROUTE_PROXIMITY = "FR24_ROUTE_PROXIMITY"
    ADS_B_GAP = "ADS_B_GAP"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_ACCESS_NODE_ONLY_STATUS = "VISIBLE_ACCESS_NODE_ONLY"

SIGNAL_WEIGHTS: dict[RoadEndSignal, float] = {
    RoadEndSignal.DEAD_END: 0.20,
    RoadEndSignal.BULB_LOOP: 0.25,
    RoadEndSignal.WIDENED_SERVICE_PAD: 0.25,
    RoadEndSignal.PULL_OFF: 0.15,
    RoadEndSignal.SWITCHBACK_TERMINUS: 0.15,
    RoadEndSignal.PATCHWORK_POI_LINK: 0.10,
    RoadEndSignal.ROUTE_LINKAGE: 0.30,
}

LINK_WEIGHTS: dict[RoadEndLink, float] = {
    RoadEndLink.PATCHWORK_POI: 0.10,
    RoadEndLink.FR24_ROUTE_PROXIMITY: 0.10,
    RoadEndLink.ADS_B_GAP: 0.10,
    RoadEndLink.REPEAT_GRIDID: 0.10,
}

SIGNAL_DEFINITIONS: dict[str, dict[str, str]] = {
    "DEAD_END": {
        "definition": "Road or track terminates without through-connection.",
        "visual_cue": "Abrupt road end, closed track, or terminal access spur.",
    },
    "BULB_LOOP": {
        "definition": "Road end expands into a loop or bulb-like turnaround.",
        "visual_cue": "Circular, oval, hook, or loop geometry.",
    },
    "WIDENED_SERVICE_PAD": {
        "definition": "Road end widens into a graded pad or work area.",
        "visual_cue": "Cleared apron, service platform, or compacted surface.",
    },
    "PULL_OFF": {
        "definition": "Small shoulder or side-node along a road used for stopping or staging.",
        "visual_cue": "Lateral widened pocket, turnout, or small holding scar.",
    },
    "SWITCHBACK_TERMINUS": {
        "definition": "Road ends at or near a switchback or serpentine grade.",
        "visual_cue": "Hairpin turn with terminal spur or access stop.",
    },
}


@dataclass(frozen=True)
class RoadEndObservation:
    node_id: str
    grid_id: str
    source_id: str
    timestamp_local: str = ""
    signals: dict[RoadEndSignal | str, float] = field(default_factory=dict)
    classes: tuple[RoadEndClass | str, ...] = ()
    links: dict[RoadEndLink | str, bool] = field(default_factory=dict)
    patchwork_poi_id: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RoadEndScore:
    node_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    classes: tuple[str, ...]
    visible_geometry_score: float
    linkage_score: float
    combined_score: float
    confidence_band: str
    access_status: str
    visible_access_only_guardrail: bool
    signals: dict[str, float]
    signal_contributions: dict[str, float]
    links: dict[str, bool]
    linked_evidence: tuple[str, ...]
    patchwork_poi_id: str
    notes: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _as_signal(value: RoadEndSignal | str) -> RoadEndSignal | None:
    if isinstance(value, RoadEndSignal):
        return value
    try:
        return RoadEndSignal(str(value))
    except ValueError:
        return None


def _as_link(value: RoadEndLink | str) -> RoadEndLink | None:
    if isinstance(value, RoadEndLink):
        return value
    try:
        return RoadEndLink(str(value))
    except ValueError:
        return None


def confidence_band(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def score_visible_geometry(signals: dict[RoadEndSignal | str, float]) -> tuple[float, dict[str, float]]:
    contributions: dict[str, float] = {}
    total = 0.0
    for raw_signal, raw_presence in signals.items():
        signal = _as_signal(raw_signal)
        if signal is None:
            continue
        if signal in {RoadEndSignal.PATCHWORK_POI_LINK, RoadEndSignal.ROUTE_LINKAGE}:
            continue
        presence = clamp01(float(raw_presence))
        contribution = round(SIGNAL_WEIGHTS.get(signal, 0.0) * presence, 4)
        contributions[signal.value] = contribution
        total += contribution
    return round(clamp01(total), 4), contributions


def score_links(links: dict[RoadEndLink | str, bool]) -> tuple[float, tuple[str, ...]]:
    evidence: list[str] = []
    total = 0.0
    for raw_link, present in links.items():
        link = _as_link(raw_link)
        if link is None or not bool(present):
            continue
        evidence.append(link.value)
        total += LINK_WEIGHTS.get(link, 0.0)
    return round(clamp01(total), 4), tuple(sorted(evidence))


def score_road_end_observation(observation: RoadEndObservation) -> RoadEndScore:
    geometry_score, contributions = score_visible_geometry(observation.signals)
    linkage_score, evidence = score_links(observation.links)
    combined = round(clamp01(geometry_score + linkage_score), 4)
    normalized_signals = {
        _enum_name(k): clamp01(float(v)) for k, v in observation.signals.items()
    }
    normalized_links = {_enum_name(k): bool(v) for k, v in observation.links.items()}
    classes = tuple(_enum_name(c) for c in observation.classes)
    return RoadEndScore(
        node_id=observation.node_id,
        grid_id=observation.grid_id,
        source_id=observation.source_id,
        timestamp_local=observation.timestamp_local,
        classes=classes,
        visible_geometry_score=geometry_score,
        linkage_score=linkage_score,
        combined_score=combined,
        confidence_band=confidence_band(combined),
        access_status=VISIBLE_ACCESS_NODE_ONLY_STATUS,
        visible_access_only_guardrail=True,
        signals=normalized_signals,
        signal_contributions=contributions,
        links=normalized_links,
        linked_evidence=evidence,
        patchwork_poi_id=observation.patchwork_poi_id,
        notes=observation.notes,
    )


def build_road_end_node_ledger(observations: list[RoadEndObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_road_end_observation(obs)
        rows.append(
            {
                "node_id": score.node_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "classes": list(score.classes),
                "visible_geometry_score": score.visible_geometry_score,
                "linkage_score": score.linkage_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "access_status": score.access_status,
                "visible_access_only_guardrail": score.visible_access_only_guardrail,
                "signals": score.signals,
                "signal_contributions": score.signal_contributions,
                "links": score.links,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "notes": score.notes,
            }
        )
    return rows


def build_p_route_confidence_patch(observations: list[RoadEndObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_road_end_observation(obs)
        rows.append(
            {
                "node_id": score.node_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "visible_geometry_score": score.visible_geometry_score,
                "linkage_score": score.linkage_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "provenance_rule": "visible_geometry_score and linkage_score remain separable",
                "guardrail_status": score.access_status,
            }
        )
    return rows


def road_end_schema() -> dict[str, Any]:
    return {
        "detector": "SATIM_ROAD_END_TURNAROUND_DETECTOR_v1",
        "guardrail": VISIBLE_ACCESS_NODE_ONLY_STATUS,
        "signals": SIGNAL_DEFINITIONS,
        "classes": [klass.value for klass in RoadEndClass],
        "links": [link.value for link in RoadEndLink],
        "confidence_bands": {"LOW": "<0.40", "MEDIUM": "0.40-0.69", "HIGH": ">=0.70"},
        "signal_weights": {signal.value: weight for signal, weight in SIGNAL_WEIGHTS.items()},
        "link_weights": {link.value: weight for link, weight in LINK_WEIGHTS.items()},
    }
