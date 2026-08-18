"""Anomaly scoring for aggregate Skywatcher sensor fusion outputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from skywatcher.core.lenses import default_registry
from skywatcher.fusion.historical_baselines import index_baselines

# These were five unnamed literals inside function bodies - two scoring weights and three
# band cutoffs - so nothing recorded where they came from or that they are unvalidated.
# They now resolve through the governed threshold registry (ADR v2.1 A2), which means each
# one carries an owner, a purpose, a validation artifact, a failure behavior, and a status
# that says out loud it is a candidate rather than a measured value.
RATIO_WEIGHT_ID = "FUSION-ANOMALY-WEIGHT-RATIO"
CONFIDENCE_WEIGHT_ID = "FUSION-ANOMALY-WEIGHT-CONFIDENCE"
BAND_HIGH_ID = "FUSION-ANOMALY-BAND-HIGH-0.80"
BAND_MODERATE_ID = "FUSION-ANOMALY-BAND-MODERATE-0.60"
BAND_LOW_ID = "FUSION-ANOMALY-BAND-LOW-0.40"

THRESHOLD_IDS = (
    RATIO_WEIGHT_ID,
    CONFIDENCE_WEIGHT_ID,
    BAND_HIGH_ID,
    BAND_MODERATE_ID,
    BAND_LOW_ID,
)


def _band(score: float) -> str:
    registry = default_registry()
    if score >= registry.value_of(BAND_HIGH_ID):
        return "high_review"
    if score >= registry.value_of(BAND_MODERATE_ID):
        return "moderate_review"
    if score >= registry.value_of(BAND_LOW_ID):
        return "low_review"
    return "suppress"


def score_against_historical_baselines(
    current_records: Iterable[Mapping[str, object]],
    baselines: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Score current aggregate records against historical baselines.

    The score is intended only to prioritize analyst review. Outputs do not
    contain operational cueing or live tracking directives.
    """

    registry = default_registry()
    ratio_weight = registry.value_of(RATIO_WEIGHT_ID)
    confidence_weight = registry.value_of(CONFIDENCE_WEIGHT_ID)
    # Attached to every scored row so a consumer can see the cutoffs behind the number
    # and their governance status, rather than a bare score with no provenance.
    thresholds_applied = registry.stamp(THRESHOLD_IDS)

    baseline_index = index_baselines(baselines)
    scored: list[dict[str, object]] = []
    for record in current_records:
        corridor_id = str(record.get("corridor_id") or "unassigned")
        domain = str(record.get("domain") or record.get("source_domain") or "context")
        baseline = baseline_index.get((corridor_id, domain), {})
        historical_count = float(baseline.get("historical_count", 0.0))
        current_count = float(record.get("event_count", 1.0))
        confidence = float(record.get("confidence", 0.0))
        ratio = 1.0 if historical_count <= 0 else current_count / historical_count
        ratio_component = min(1.0, max(0.0, abs(ratio - 1.0)))
        confidence_component = min(1.0, max(0.0, confidence))
        anomaly_score = round(
            (ratio_weight * ratio_component) + (confidence_weight * confidence_component), 3
        )
        band = _band(anomaly_score)
        if band == "suppress":
            continue
        scored.append({
            "anomaly_id": f"anom_{corridor_id}_{domain}_{len(scored) + 1}",
            "corridor_id": corridor_id,
            "domain": domain,
            "current_count": current_count,
            "historical_count": historical_count,
            "ratio": round(ratio, 3),
            "confidence": confidence,
            "anomaly_score": anomaly_score,
            "review_band": band,
            "operator_action": "review_context_only",
            "live_tracking": False,
            "operational_cueing": False,
            "thresholds_applied": thresholds_applied,
        })
    return scored
