"""Hybrid provenance classifier for FR24 route segments.

The classifier separates visual rendering from source/transmission inference.
A bright route color never vetoes an offline or interpolation assessment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

DEFAULT_WEIGHTS = {
    "temporal_gap": 0.30,
    "interpolation_geometry": 0.24,
    "sampling_density_deficit": 0.16,
    "endpoint_discontinuity": 0.12,
    "telemetry_discontinuity": 0.10,
    "source_transition": 0.05,
    "dark_gap_rendering": 0.03,
}


@dataclass(frozen=True)
class SegmentSignals:
    temporal_gap: float = 0.0
    interpolation_geometry: float = 0.0
    sampling_density_deficit: float = 0.0
    endpoint_discontinuity: float = 0.0
    telemetry_discontinuity: float = 0.0
    source_transition: float = 0.0
    dark_gap_rendering: float = 0.0
    route_color: str = "unknown"
    screenshot_only: bool = False
    corroborated_offline: bool = False
    continuous_structured_track: bool = False
    alternate_source_continuity: bool = False


@dataclass(frozen=True)
class SegmentAssessment:
    schema_version: str
    offline_score: float
    non_color_signal_count: int
    visual_render_state: str
    source_state: str
    transmission_state: str
    final_classification: str
    confidence: float
    review_required: bool
    component_scores: Mapping[str, float] = field(default_factory=dict)
    reasons: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def assess_segment(
    signals: SegmentSignals,
    *,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    interpolation_threshold: float = 0.40,
    probable_offline_threshold: float = 0.62,
    minimum_non_color_signals: int = 2,
    screenshot_only_confidence_cap: float = 0.79,
) -> SegmentAssessment:
    scores = {name: _bounded(getattr(signals, name)) for name in DEFAULT_WEIGHTS}
    offline_score = sum(scores[name] * float(weights[name]) for name in DEFAULT_WEIGHTS)
    offline_score = _bounded(offline_score)

    non_color_names = tuple(name for name in DEFAULT_WEIGHTS if name != "dark_gap_rendering")
    non_color_count = sum(scores[name] >= 0.50 for name in non_color_names)
    reasons = [name for name, score in scores.items() if score >= 0.50]

    visual = "DARK_ROUTE" if scores["dark_gap_rendering"] >= 0.50 else (
        "BRIGHT_ROUTE" if signals.route_color not in {"", "unknown", "dark"} else "UNKNOWN"
    )

    if signals.alternate_source_continuity:
        source_state = "SOURCE_TRANSITION"
        transmission_state = "NOT_ASSESSABLE"
        final = "SOURCE_TRANSITION"
        confidence = max(offline_score, scores["source_transition"])
    elif signals.continuous_structured_track:
        source_state = "CONTINUOUS_ADSB"
        transmission_state = "OBSERVED_TRANSMITTING"
        final = "OBSERVED_TRACK"
        confidence = max(0.70, 1.0 - offline_score)
    elif signals.corroborated_offline:
        source_state = "DISCONTINUOUS"
        transmission_state = "CONFIRMED_SIGNAL_GAP"
        final = "CONFIRMED_OFFLINE"
        confidence = max(0.82, offline_score)
    elif non_color_count >= minimum_non_color_signals and offline_score >= probable_offline_threshold:
        source_state = "DISCONTINUOUS"
        transmission_state = "PROBABLE_SIGNAL_GAP"
        final = "PROBABLE_OFFLINE"
        confidence = offline_score
    elif offline_score >= interpolation_threshold:
        source_state = "INTERPOLATED"
        transmission_state = "NOT_ASSESSABLE"
        final = "INTERPOLATED"
        confidence = offline_score
    else:
        source_state = "UNKNOWN"
        transmission_state = "NOT_ASSESSABLE"
        final = "UNKNOWN"
        confidence = max(0.0, 1.0 - offline_score)

    if signals.screenshot_only:
        confidence = min(confidence, screenshot_only_confidence_cap)

    review_required = final in {"INTERPOLATED", "PROBABLE_OFFLINE", "SOURCE_TRANSITION", "UNKNOWN"}
    return SegmentAssessment(
        schema_version="fr24.segment.provenance.v1",
        offline_score=round(offline_score, 6),
        non_color_signal_count=non_color_count,
        visual_render_state=visual,
        source_state=source_state,
        transmission_state=transmission_state,
        final_classification=final,
        confidence=round(_bounded(confidence), 6),
        review_required=review_required,
        component_scores=scores,
        reasons=tuple(reasons),
    )
