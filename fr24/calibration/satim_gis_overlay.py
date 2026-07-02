"""SATIM Phase 2 GIS overlay scoring stub.

This module patches SATIM visual-ledger candidates with normalized GIS alignment
scores. It intentionally avoids mandatory GeoPandas/Shapely dependencies in the
stub: callers provide layer overlap metrics, and future spatial adapters can
compute those metrics from real geometries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

GIS_SCORE_FIELDS = {
    "road_alignment",
    "building_alignment",
    "airport_alignment",
    "parcel_alignment",
    "terrain_crossing",
    "coastal_crossing_score",
    "landcover_persistence",
}


@dataclass(frozen=True)
class GisOverlayConfig:
    infrastructure_weight_road: float = 0.30
    infrastructure_weight_building: float = 0.25
    infrastructure_weight_airport: float = 0.25
    infrastructure_weight_parcel: float = 0.20


def clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def infrastructure_alignment_score(scores: Mapping[str, Any], config: GisOverlayConfig | None = None) -> float:
    """Aggregate infrastructure alignment as weighted explanatory evidence."""
    cfg = config or GisOverlayConfig()
    return clamp01(
        cfg.infrastructure_weight_road * clamp01(scores.get("road_alignment"))
        + cfg.infrastructure_weight_building * clamp01(scores.get("building_alignment"))
        + cfg.infrastructure_weight_airport * clamp01(scores.get("airport_alignment"))
        + cfg.infrastructure_weight_parcel * clamp01(scores.get("parcel_alignment"))
    )


def patch_candidate_with_gis_scores(
    candidate: Mapping[str, Any],
    overlay_scores: Mapping[str, Any],
    *,
    config: GisOverlayConfig | None = None,
) -> dict[str, Any]:
    """Return a candidate row with GIS-derived feature scores merged in."""
    patched = dict(candidate)
    feature_scores = dict(candidate.get("feature_scores") or {})
    for field in GIS_SCORE_FIELDS:
        if field in overlay_scores:
            feature_scores[field] = clamp01(overlay_scores[field])
    feature_scores["infrastructure_alignment"] = infrastructure_alignment_score(feature_scores, config=config)
    patched["feature_scores"] = feature_scores

    flags = list(candidate.get("contradiction_flags") or [])
    if feature_scores["infrastructure_alignment"] >= 0.65 and candidate.get("classification") == "probable_tile_seam":
        if "infrastructure_explains_boundary" not in flags:
            flags.append("infrastructure_explains_boundary")
        patched["review_state"] = "needs_review"
    patched["contradiction_flags"] = flags
    return patched


def overlay_score_patch_from_metrics(metrics: Mapping[str, Any]) -> dict[str, float]:
    """Normalize raw spatial metrics into SATIM GIS score fields."""
    return {
        "road_alignment": clamp01(metrics.get("road_overlap_fraction")),
        "building_alignment": clamp01(metrics.get("building_overlap_fraction")),
        "airport_alignment": clamp01(metrics.get("airport_overlap_fraction")),
        "parcel_alignment": clamp01(metrics.get("parcel_edge_alignment")),
        "terrain_crossing": clamp01(metrics.get("terrain_crossing")),
        "coastal_crossing_score": clamp01(metrics.get("coastal_crossing_score")),
        "landcover_persistence": clamp01(metrics.get("landcover_persistence")),
    }
