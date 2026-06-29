"""SATIM maintained patchwork clearing detector.

This module scores visible surface texture only. It is designed for SATIM
screenshots/satellite-derived observations where low canopy, exposed soil,
internal dirt roads, patch boundaries, road ends, and cut/fill exposure form a
managed patchwork landscape.

Guardrail: this module never infers subsurface, covert, or ILAP function from
texture alone. It emits POI candidates and a separable P-Route confidence patch
when flight-behavior linkage evidence is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PatchworkSignal(str, Enum):
    LOW_CANOPY_MANAGED_SURFACE = "LOW_CANOPY_MANAGED_SURFACE"
    DIRT_SERVICE_ROAD_NETWORK = "DIRT_SERVICE_ROAD_NETWORK"
    PATCH_BOUNDARY_GEOMETRY = "PATCH_BOUNDARY_GEOMETRY"
    ROAD_END_TURNAROUND = "ROAD_END_TURNAROUND"
    CUT_FILL_EXPOSURE = "CUT_FILL_EXPOSURE"
    INFRASTRUCTURE_ADJACENCY = "INFRASTRUCTURE_ADJACENCY"
    REPEAT_FR24_GRID_PROXIMITY = "REPEAT_FR24_GRID_PROXIMITY"


class PatchworkClass(str, Enum):
    AGRICULTURAL_CLEARING = "AGRICULTURAL_CLEARING"
    LANDFILL_EDGE = "LANDFILL_EDGE"
    QUARRY_OR_BORROW_PIT = "QUARRY_OR_BORROW_PIT"
    UTILITY_ACCESS = "UTILITY_ACCESS"
    RECREATIONAL_MUNICIPAL_EDGE = "RECREATIONAL_MUNICIPAL_EDGE"
    PRIVATE_ACCESS_COMPOUND = "PRIVATE_ACCESS_COMPOUND"


class FlightLink(str, Enum):
    FR24_ROUTE_PROXIMITY = "FR24_ROUTE_PROXIMITY"
    ADS_B_GAP = "ADS_B_GAP"
    LOITER_HOVER = "LOITER_HOVER"
    REPEAT_GRIDID = "REPEAT_GRIDID"


VISIBLE_SURFACE_ONLY_STATUS = "POI_ONLY_UNTIL_ROUTE_CORRELATION"

SIGNAL_WEIGHTS: dict[PatchworkSignal, float] = {
    PatchworkSignal.LOW_CANOPY_MANAGED_SURFACE: 0.20,
    PatchworkSignal.DIRT_SERVICE_ROAD_NETWORK: 0.25,
    PatchworkSignal.PATCH_BOUNDARY_GEOMETRY: 0.10,
    PatchworkSignal.ROAD_END_TURNAROUND: 0.20,
    PatchworkSignal.CUT_FILL_EXPOSURE: 0.15,
    PatchworkSignal.INFRASTRUCTURE_ADJACENCY: 0.10,
    PatchworkSignal.REPEAT_FR24_GRID_PROXIMITY: 0.30,
}

LINK_WEIGHTS: dict[FlightLink, float] = {
    FlightLink.FR24_ROUTE_PROXIMITY: 0.10,
    FlightLink.ADS_B_GAP: 0.10,
    FlightLink.LOITER_HOVER: 0.10,
    FlightLink.REPEAT_GRIDID: 0.10,
}

SIGNAL_DEFINITIONS: dict[str, dict[str, str]] = {
    "LOW_CANOPY_MANAGED_SURFACE": {
        "definition": "Maintained low vegetation, grass/scrub, exposed soil, or repeatedly cleared parcel surface.",
        "visual_cue": "Low tree canopy, smooth green/brown texture, mowing or clearing edge.",
    },
    "DIRT_SERVICE_ROAD_NETWORK": {
        "definition": "Unpaved access roads or internal circulation paths.",
        "visual_cue": "Pale/tan roads, switchbacks, spurs, loops, or service-road traces.",
    },
    "PATCH_BOUNDARY_GEOMETRY": {
        "definition": "Parcel-like divisions caused by roads, tracks, vegetation edges, drainage, or clearing lines.",
        "visual_cue": "Curved or rectilinear patch outlines separating green/brown surfaces.",
    },
    "ROAD_END_TURNAROUND": {
        "definition": "Road terminus, bulb, loop, service pad, staging point, or pull-off.",
        "visual_cue": "Dead-end, circular turnaround, widened dirt node, or service pad.",
    },
    "CUT_FILL_EXPOSURE": {
        "definition": "Exposed soil/rock, slope cut, fill pile, borrow face, quarry/landfill-like surface disturbance.",
        "visual_cue": "Bright soil/rock, scarps, piles, excavation margins, or graded fill.",
    },
}


@dataclass(frozen=True)
class PatchworkObservation:
    """Human- or model-extracted visible surface observations for one POI."""

    poi_id: str
    grid_id: str
    source_id: str
    timestamp_local: str = ""
    signals: dict[PatchworkSignal | str, float] = field(default_factory=dict)
    classes: tuple[PatchworkClass | str, ...] = ()
    flight_links: dict[FlightLink | str, bool] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class PatchworkScore:
    poi_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    classes: tuple[str, ...]
    visual_surface_score: float
    flight_link_score: float
    combined_score: float
    confidence_band: str
    ilap_status: str
    visible_surface_only_guardrail: bool
    signals: dict[str, float]
    signal_contributions: dict[str, float]
    flight_links: dict[str, bool]
    linked_route_evidence: tuple[str, ...]
    notes: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _as_signal(value: PatchworkSignal | str) -> PatchworkSignal | None:
    if isinstance(value, PatchworkSignal):
        return value
    try:
        return PatchworkSignal(str(value))
    except ValueError:
        return None


def _as_link(value: FlightLink | str) -> FlightLink | None:
    if isinstance(value, FlightLink):
        return value
    try:
        return FlightLink(str(value))
    except ValueError:
        return None


def confidence_band(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def score_visible_surface(signals: dict[PatchworkSignal | str, float]) -> tuple[float, dict[str, float]]:
    """Score visible surface signals only, preserving per-signal contributions."""
    contributions: dict[str, float] = {}
    total = 0.0
    for raw_signal, raw_presence in signals.items():
        signal = _as_signal(raw_signal)
        if signal is None:
            continue
        presence = clamp01(float(raw_presence))
        contribution = round(SIGNAL_WEIGHTS.get(signal, 0.0) * presence, 4)
        contributions[signal.value] = contribution
        total += contribution
    return round(clamp01(total), 4), contributions


def score_flight_links(flight_links: dict[FlightLink | str, bool]) -> tuple[float, tuple[str, ...]]:
    """Score route-correlation linkage separately from the visual score."""
    evidence: list[str] = []
    total = 0.0
    for raw_link, present in flight_links.items():
        link = _as_link(raw_link)
        if link is None or not bool(present):
            continue
        evidence.append(link.value)
        total += LINK_WEIGHTS.get(link, 0.0)
    return round(clamp01(total), 4), tuple(sorted(evidence))


def score_patchwork_observation(observation: PatchworkObservation) -> PatchworkScore:
    """Return the POI score and P-Route patch inputs for one observation.

    The returned ``ilap_status`` remains ``POI_ONLY_UNTIL_ROUTE_CORRELATION`` even
    when route links exist; promotion to any downstream ILAP class must happen in
    a separate human-reviewed correlation layer.
    """
    visual_score, contributions = score_visible_surface(observation.signals)
    link_score, evidence = score_flight_links(observation.flight_links)
    combined = round(clamp01(visual_score + link_score), 4)
    normalized_signals = {
        _enum_name(k): clamp01(float(v)) for k, v in observation.signals.items()
    }
    normalized_links = {_enum_name(k): bool(v) for k, v in observation.flight_links.items()}
    classes = tuple(_enum_name(c) for c in observation.classes)
    return PatchworkScore(
        poi_id=observation.poi_id,
        grid_id=observation.grid_id,
        source_id=observation.source_id,
        timestamp_local=observation.timestamp_local,
        classes=classes,
        visual_surface_score=visual_score,
        flight_link_score=link_score,
        combined_score=combined,
        confidence_band=confidence_band(combined),
        ilap_status=VISIBLE_SURFACE_ONLY_STATUS,
        visible_surface_only_guardrail=True,
        signals=normalized_signals,
        signal_contributions=contributions,
        flight_links=normalized_links,
        linked_route_evidence=evidence,
        notes=observation.notes,
    )


def build_patchwork_poi_ledger(observations: list[PatchworkObservation]) -> list[dict[str, Any]]:
    """Build SATIM_PATCHWORK_POI_LEDGER rows."""
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_patchwork_observation(obs)
        rows.append(
            {
                "poi_id": score.poi_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "classes": list(score.classes),
                "visual_surface_score": score.visual_surface_score,
                "flight_link_score": score.flight_link_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "ilap_status": score.ilap_status,
                "visible_surface_only_guardrail": score.visible_surface_only_guardrail,
                "signals": score.signals,
                "signal_contributions": score.signal_contributions,
                "flight_links": score.flight_links,
                "linked_route_evidence": list(score.linked_route_evidence),
                "notes": score.notes,
            }
        )
    return rows


def build_p_route_confidence_patch(observations: list[PatchworkObservation]) -> list[dict[str, Any]]:
    """Build P_ROUTE_CONFIDENCE_PATCH rows while keeping score provenance split."""
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_patchwork_observation(obs)
        rows.append(
            {
                "poi_id": score.poi_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "visual_surface_score": score.visual_surface_score,
                "flight_link_score": score.flight_link_score,
                "combined_score": score.combined_score,
                "confidence_band": score.confidence_band,
                "linked_route_evidence": list(score.linked_route_evidence),
                "provenance_rule": "visual_surface_score and flight_link_score remain separable",
                "guardrail_status": score.ilap_status,
            }
        )
    return rows


def patchwork_schema() -> dict[str, Any]:
    """Frontend/documentation schema for SATIM patchwork detector outputs."""
    return {
        "detector": "SATIM_MAINTAINED_PATCHWORK_CLEARING_DETECTOR_v1",
        "guardrail": VISIBLE_SURFACE_ONLY_STATUS,
        "signals": SIGNAL_DEFINITIONS,
        "classes": [klass.value for klass in PatchworkClass],
        "flight_links": [link.value for link in FlightLink],
        "confidence_bands": {"LOW": "<0.40", "MEDIUM": "0.40-0.69", "HIGH": ">=0.70"},
        "signal_weights": {signal.value: weight for signal, weight in SIGNAL_WEIGHTS.items()},
        "link_weights": {link.value: weight for link, weight in LINK_WEIGHTS.items()},
    }
