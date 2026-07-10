from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactSignal(str, Enum):
    TILE_SEAM = "TILE_SEAM"
    ORTHO_MOSAIC_BOUNDARY = "ORTHO_MOSAIC_BOUNDARY"
    BLUR_EDGE = "BLUR_EDGE"
    EPOCH_MISMATCH = "EPOCH_MISMATCH"
    COLOR_BALANCE_SHIFT = "COLOR_BALANCE_SHIFT"
    PARALLAX_OFFSET = "PARALLAX_OFFSET"
    CROSSES_UNRELATED_TERRAIN = "CROSSES_UNRELATED_TERRAIN"
    CANDIDATE_BOUNDARY_COINCIDENCE = "CANDIDATE_BOUNDARY_COINCIDENCE"


class ArtifactClass(str, Enum):
    IMAGERY_ARTIFACT = "IMAGERY_ARTIFACT"
    TRUE_SURFACE_FEATURE = "TRUE_SURFACE_FEATURE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ArtifactLink(str, Enum):
    PATCHWORK_POI = "PATCHWORK_POI"
    ROAD_END_NODE = "ROAD_END_NODE"
    CUT_FILL_FEATURE = "CUT_FILL_FEATURE"


NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS = "NON_DESTRUCTIVE_CONFIDENCE_PATCH"

SIGNAL_WEIGHTS: dict[ArtifactSignal, float] = {
    ArtifactSignal.TILE_SEAM: 0.25,
    ArtifactSignal.ORTHO_MOSAIC_BOUNDARY: 0.20,
    ArtifactSignal.BLUR_EDGE: 0.15,
    ArtifactSignal.EPOCH_MISMATCH: 0.20,
    ArtifactSignal.COLOR_BALANCE_SHIFT: 0.15,
    ArtifactSignal.PARALLAX_OFFSET: 0.15,
    ArtifactSignal.CROSSES_UNRELATED_TERRAIN: 0.10,
    ArtifactSignal.CANDIDATE_BOUNDARY_COINCIDENCE: 0.10,
}

LINK_WEIGHTS: dict[ArtifactLink, float] = {
    ArtifactLink.PATCHWORK_POI: 0.05,
    ArtifactLink.ROAD_END_NODE: 0.05,
    ArtifactLink.CUT_FILL_FEATURE: 0.05,
}

SIGNAL_DEFINITIONS: dict[str, dict[str, str]] = {
    "TILE_SEAM": {
        "definition": "Hard boundary between adjacent imagery tiles.",
        "visual_cue": "Straight or rectangular line crossing terrain without matching surface features.",
    },
    "ORTHO_MOSAIC_BOUNDARY": {
        "definition": "Boundary where orthophoto tiles were stitched.",
        "visual_cue": "Abrupt tonal or texture transition over a tile edge.",
    },
    "BLUR_EDGE": {
        "definition": "Resolution or focus discontinuity.",
        "visual_cue": "One side sharper or blurrier than adjacent area.",
    },
    "EPOCH_MISMATCH": {
        "definition": "Adjacent imagery captured at different times.",
        "visual_cue": "Vegetation, construction, road, or water state changes across seam.",
    },
    "COLOR_BALANCE_SHIFT": {
        "definition": "Radiometric mismatch between imagery tiles.",
        "visual_cue": "Sudden brightness, hue, saturation, or contrast shift.",
    },
    "PARALLAX_OFFSET": {
        "definition": "Apparent displacement caused by viewing geometry.",
        "visual_cue": "Misaligned roads, roofs, poles, slopes, or tall features.",
    },
}


@dataclass(frozen=True)
class ArtifactObservation:
    artifact_id: str
    grid_id: str
    source_id: str
    timestamp_local: str = ""
    signals: dict[ArtifactSignal | str, float] = field(default_factory=dict)
    classes: tuple[ArtifactClass | str, ...] = ()
    links: dict[ArtifactLink | str, bool] = field(default_factory=dict)
    patchwork_poi_id: str = ""
    road_end_node_id: str = ""
    cut_fill_feature_id: str = ""
    original_detector_score: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class ArtifactScore:
    artifact_id: str
    grid_id: str
    source_id: str
    timestamp_local: str
    classes: tuple[str, ...]
    artifact_score: float
    linkage_score: float
    combined_artifact_score: float
    confidence_band: str
    patch_status: str
    non_destructive_patch: bool
    original_detector_score: float | None
    adjusted_detector_score: float | None
    signals: dict[str, float]
    signal_contributions: dict[str, float]
    links: dict[str, bool]
    linked_evidence: tuple[str, ...]
    patchwork_poi_id: str
    road_end_node_id: str
    cut_fill_feature_id: str
    notes: str


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _enum_name(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _as_signal(value: ArtifactSignal | str) -> ArtifactSignal | None:
    if isinstance(value, ArtifactSignal):
        return value
    try:
        return ArtifactSignal(str(value))
    except ValueError:
        return None


def _as_link(value: ArtifactLink | str) -> ArtifactLink | None:
    if isinstance(value, ArtifactLink):
        return value
    try:
        return ArtifactLink(str(value))
    except ValueError:
        return None


def confidence_band(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def recommended_class(score: float) -> ArtifactClass:
    if score >= 0.70:
        return ArtifactClass.IMAGERY_ARTIFACT
    if score >= 0.40:
        return ArtifactClass.REVIEW_REQUIRED
    return ArtifactClass.TRUE_SURFACE_FEATURE


def score_artifact_signals(signals: dict[ArtifactSignal | str, float]) -> tuple[float, dict[str, float]]:
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


def score_links(links: dict[ArtifactLink | str, bool]) -> tuple[float, tuple[str, ...]]:
    evidence: list[str] = []
    total = 0.0
    for raw_link, present in links.items():
        link = _as_link(raw_link)
        if link is None or not bool(present):
            continue
        evidence.append(link.value)
        total += LINK_WEIGHTS.get(link, 0.0)
    return round(clamp01(total), 4), tuple(sorted(evidence))


def adjusted_detector_score(original_score: float | None, artifact_score: float) -> float | None:
    if original_score is None:
        return None
    return round(clamp01(float(original_score) * (1.0 - clamp01(artifact_score) * 0.5)), 4)


def score_artifact_observation(observation: ArtifactObservation) -> ArtifactScore:
    artifact_score, contributions = score_artifact_signals(observation.signals)
    linkage_score, evidence = score_links(observation.links)
    combined = round(clamp01(artifact_score + linkage_score), 4)
    classes = tuple(_enum_name(c) for c in observation.classes) or (recommended_class(combined).value,)
    normalized_signals = {
        _enum_name(k): clamp01(float(v)) for k, v in observation.signals.items()
    }
    normalized_links = {_enum_name(k): bool(v) for k, v in observation.links.items()}
    return ArtifactScore(
        artifact_id=observation.artifact_id,
        grid_id=observation.grid_id,
        source_id=observation.source_id,
        timestamp_local=observation.timestamp_local,
        classes=classes,
        artifact_score=artifact_score,
        linkage_score=linkage_score,
        combined_artifact_score=combined,
        confidence_band=confidence_band(combined),
        patch_status=NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS,
        non_destructive_patch=True,
        original_detector_score=observation.original_detector_score,
        adjusted_detector_score=adjusted_detector_score(observation.original_detector_score, combined),
        signals=normalized_signals,
        signal_contributions=contributions,
        links=normalized_links,
        linked_evidence=evidence,
        patchwork_poi_id=observation.patchwork_poi_id,
        road_end_node_id=observation.road_end_node_id,
        cut_fill_feature_id=observation.cut_fill_feature_id,
        notes=observation.notes,
    )


def build_artifact_filter_ledger(observations: list[ArtifactObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_artifact_observation(obs)
        rows.append(
            {
                "artifact_id": score.artifact_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "classes": list(score.classes),
                "artifact_score": score.artifact_score,
                "linkage_score": score.linkage_score,
                "combined_artifact_score": score.combined_artifact_score,
                "confidence_band": score.confidence_band,
                "patch_status": score.patch_status,
                "non_destructive_patch": score.non_destructive_patch,
                "original_detector_score": score.original_detector_score,
                "adjusted_detector_score": score.adjusted_detector_score,
                "signals": score.signals,
                "signal_contributions": score.signal_contributions,
                "links": score.links,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "road_end_node_id": score.road_end_node_id,
                "cut_fill_feature_id": score.cut_fill_feature_id,
                "notes": score.notes,
            }
        )
    return rows


def build_detector_confidence_patch(observations: list[ArtifactObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations:
        score = score_artifact_observation(obs)
        rows.append(
            {
                "artifact_id": score.artifact_id,
                "grid_id": score.grid_id,
                "source_id": score.source_id,
                "timestamp_local": score.timestamp_local,
                "artifact_score": score.artifact_score,
                "linkage_score": score.linkage_score,
                "combined_artifact_score": score.combined_artifact_score,
                "confidence_band": score.confidence_band,
                "original_detector_score": score.original_detector_score,
                "adjusted_detector_score": score.adjusted_detector_score,
                "linked_evidence": list(score.linked_evidence),
                "patchwork_poi_id": score.patchwork_poi_id,
                "road_end_node_id": score.road_end_node_id,
                "cut_fill_feature_id": score.cut_fill_feature_id,
                "provenance_rule": "artifact_score and original_detector_score remain separable",
                "mutation_rule": "candidate retained; emit confidence patch only",
                "patch_status": score.patch_status,
            }
        )
    return rows


def artifact_filter_schema() -> dict[str, Any]:
    return {
        "filter": "SATIM_TILE_SEAM_AND_MOSAIC_ARTIFACT_FILTER_v1",
        "guardrail": NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS,
        "signals": SIGNAL_DEFINITIONS,
        "classes": [klass.value for klass in ArtifactClass],
        "links": [link.value for link in ArtifactLink],
        "confidence_bands": {"LOW": "<0.40", "MEDIUM": "0.40-0.69", "HIGH": ">=0.70"},
        "signal_weights": {signal.value: weight for signal, weight in SIGNAL_WEIGHTS.items()},
        "link_weights": {link.value: weight for link, weight in LINK_WEIGHTS.items()},
        "adjustment_rule": "adjusted score is advisory; original score is preserved",
    }
