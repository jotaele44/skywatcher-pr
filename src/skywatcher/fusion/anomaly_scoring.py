"""Anomaly scoring for aggregate Skywatcher sensor fusion outputs."""

from __future__ import annotations

from typing import Iterable, Mapping

from skywatcher.fusion.historical_baselines import index_baselines


def _band(score: float) -> str:
    if score >= 0.80:
        return "high_review"
    if score >= 0.60:
        return "moderate_review"
    if score >= 0.40:
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

    baseline_index = index_baselines(baselines)
    scored: list[dict[str, object]] = []
    for record in current_records:
        corridor_id = str(record.get("corridor_id") or "unassigned")
        domain = str(record.get("domain") or record.get("source_domain") or "context")
        baseline = baseline_index.get((corridor_id, domain), {})
        historical_count = float(baseline.get("historical_count", 0.0))
        current_count = float(record.get("event_count", 1.0))
        confidence = float(record.get("confidence", 0.0))
        if historical_count <= 0:
            ratio = 1.0
        else:
            ratio = current_count / historical_count
        ratio_component = min(1.0, max(0.0, abs(ratio - 1.0)))
        confidence_component = min(1.0, max(0.0, confidence))
        anomaly_score = round((0.65 * ratio_component) + (0.35 * confidence_component), 3)
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
        })
    return scored
