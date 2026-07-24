"""L5 SATIM calibration: tile seam vs cloud/shadow/terrain artifact scoring."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .models import LayerCalibrationResult, write_json

DECISIONS = {
    "probable_tile_seam",
    "probable_cloud_shadow",
    "probable_terrain_shadow",
    "probable_ground_feature",
    "explainable_infrastructure",
    "indeterminate",
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def score(row: Mapping[str, Any], *names: str) -> float:
    values: list[float] = []
    for name in names:
        try:
            values.append(float(row.get(name, 0) or 0))
        except (TypeError, ValueError):
            values.append(0.0)
    return clamp01(max(values) if values else 0.0)


def context_suppression_score(row: Mapping[str, Any]) -> float:
    """Return how strongly visible context explains orthogonal geometry.

    Right angles are weak evidence by themselves. Roads, runways, reservoirs,
    treatment plants, quarries, parcels, and buildings can all create true
    orthogonal geometry, so these context signals suppress tile-seam promotion.
    """
    return score(
        row,
        "context_suppression_score",
        "infrastructure_alignment",
        "road_alignment",
        "runway_alignment",
        "water_edge_alignment",
        "reservoir_edge_alignment",
        "utility_plant_alignment",
        "quarry_alignment",
        "excavation_alignment",
        "parcel_boundary_alignment",
        "building_alignment",
    )


def corroborating_tile_signal_count(
    *,
    straight: float,
    radiometric: float,
    texture: float,
    rectangular: float,
    persistence: float,
    terrain: float,
) -> int:
    """Count tile-seam signals excluding the weak right-angle prior."""
    signals = [
        straight >= 0.55,
        radiometric >= 0.55,
        texture >= 0.55,
        rectangular >= 0.55,
        persistence <= 0.35,
        terrain <= 0.35,
    ]
    return sum(1 for item in signals if item)


def classify_candidate(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify one candidate from normalized feature scores.

    Existing columns remain supported:
    straight_boundary_score, radiometric_discontinuity_score,
    cloud_mask_intersection, shadow_mask_intersection, dem_hillshade_alignment,
    multi_date_persistence, infrastructure_alignment.

    Additional L5 orthogonal-artifact columns:
    right_angle_score, orthogonal_corner_score, straight_edge_score,
    rectangular_patch_score, color_discontinuity_score,
    texture_discontinuity_score, context_suppression_score.

    Rule:
    - 90-degree/orthogonal geometry is a weak prior.
    - Candidate tile seam requires at least two corroborating non-angle signals.
    - Visible infrastructure/land-use context suppresses tile-seam promotion.
    """
    straight = score(row, "straight_boundary_score", "straight_edge_score")
    radiometric = score(row, "radiometric_discontinuity_score", "color_discontinuity_score")
    texture = score(row, "texture_discontinuity_score")
    cloud = score(row, "cloud_mask_intersection")
    shadow = score(row, "shadow_mask_intersection")
    terrain = score(row, "dem_hillshade_alignment")
    persistence = score(row, "multi_date_persistence")
    infrastructure = score(row, "infrastructure_alignment")
    suppression = context_suppression_score(row)
    right_angle = score(row, "right_angle_score", "orthogonal_corner_score")
    rectangular = score(row, "rectangular_patch_score")

    corroborating = corroborating_tile_signal_count(
        straight=straight,
        radiometric=radiometric,
        texture=texture,
        rectangular=rectangular,
        persistence=persistence,
        terrain=terrain,
    )

    tile_base = clamp01(
        (0.28 * straight)
        + (0.27 * radiometric)
        + (0.10 * texture)
        + (0.10 * rectangular)
        + (0.05 * right_angle)
        + (0.15 * (1.0 - persistence))
        + (0.15 * (1.0 - terrain))
    )

    # Orthogonal geometry alone must not promote a seam.
    if right_angle >= 0.55 and corroborating < 2:
        tile_base = min(tile_base, 0.49)

    tile = clamp01(tile_base * (1.0 - (0.45 * suppression)))
    cloud_shadow = clamp01(max(cloud, shadow) * max(radiometric, texture, 0.1))
    terrain_shadow = clamp01(terrain * max(shadow, radiometric, texture))
    ground = clamp01((persistence + infrastructure + suppression + (1.0 - max(cloud, shadow))) / 4.0)

    scores = {
        "tile_seam_likelihood": tile,
        "cloud_shadow_likelihood": cloud_shadow,
        "terrain_shadow_likelihood": terrain_shadow,
        "persistent_ground_feature_likelihood": ground,
        "orthogonal_artifact_score": right_angle,
        "rectangular_patch_score": rectangular,
        "context_suppression_score": suppression,
        "tile_corroborating_signal_count": corroborating,
    }

    if suppression >= 0.70 and right_angle >= 0.55 and tile_base >= 0.45:
        decision = "explainable_infrastructure"
    else:
        decision_scores = {
            "probable_tile_seam": tile,
            "probable_cloud_shadow": cloud_shadow,
            "probable_terrain_shadow": terrain_shadow,
            "probable_ground_feature": ground,
        }
        decision = max(decision_scores, key=decision_scores.get)
        if decision_scores[decision] < 0.55:
            decision = "indeterminate"

    return {**scores, "decision": decision}


def load_candidates(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(results)
    counts = {decision: 0 for decision in DECISIONS}
    for row in rows:
        decision = str(row.get("decision", "indeterminate"))
        counts[decision] = counts.get(decision, 0) + 1
    return {"candidate_count": len(rows), "decision_counts": counts}


def calibrate(candidates_csv: str) -> Dict[str, Any]:
    candidates = load_candidates(candidates_csv)
    scored = [classify_candidate(row) for row in candidates]
    metrics = summarize(scored)
    findings = []
    if not candidates:
        findings.append({"severity": "warning", "detail": "no tile seam/shadow calibration candidates found"})
    status = "READY" if candidates else "MISSING"
    return LayerCalibrationResult(
        layer="L5_tile_seam_shadow",
        status=status,
        metrics=metrics,
        thresholds={
            "promotion_min_likelihood": 0.55,
            "orthogonal_artifact_rule": "right angles are weak priors requiring at least two corroborating seam signals",
            "tile_seam_rule": "straight/rectangular boundary + radiometric or texture discontinuity + non-persistence + no terrain alignment",
            "context_suppressors": "roads, runways, reservoirs, utility plants, quarries, parcels, and buildings suppress seam promotion",
            "ground_feature_rule": "multi-date persistence + infrastructure/landcover alignment + low cloud/shadow intersection",
        },
        findings=findings,
    ).to_dict()


# ---------------------------------------------------------------------------
# Strict tile-seam AND-gate (docs/SATIM_TRACK_LINE_VS_TILE_SEAM_RULES.md)
# ---------------------------------------------------------------------------
# The spec's conjunctive rule, stricter than the default weighted classifier.
STRICT_STRAIGHTNESS_MIN = 0.85
STRICT_RADIOMETRIC_MIN = 0.55
STRICT_SCREEN_LOCKED_MIN = 0.70
STRICT_PERSISTENCE_MAX = 0.35
STRICT_TERRAIN_SHADOW_MAX = 0.55
STRICT_GROUND_FEATURE_MAX = 0.55
STRICT_OVERLAP_SUPPRESS = 0.55


def classify_candidate_strict(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Spec-faithful conjunctive tile-seam gate.

    A candidate is ``probable_tile_seam`` only if ALL hold:
      straightness >= 0.85, radiometric_delta >= 0.55, screen_locked_score >= 0.70,
      multi_date_persistence < 0.35, terrain_shadow_likelihood < 0.55,
      persistent_ground_feature_likelihood < 0.55,
    and neither track_line_overlap nor ui_overlay_overlap is high (>= 0.55).

    NOTE: ``screen_locked_score`` has no feature extractor yet (candidate rows
    default it to 0.0), so in production this gate promotes nothing until that
    feature is produced — the honest, spec-faithful behaviour. The derived
    likelihoods reuse :func:`classify_candidate`.
    """
    base = classify_candidate(row)
    straightness = score(row, "straightness", "straight_boundary_score", "straight_edge_score")
    radiometric = score(row, "radiometric_delta", "radiometric_discontinuity_score", "color_discontinuity_score")
    screen_locked = score(row, "screen_locked_score")
    persistence = score(row, "multi_date_persistence")
    track_line_overlap = score(row, "track_line_overlap")
    ui_overlay_overlap = score(row, "ui_overlay_overlap")
    terrain_shadow = float(base["terrain_shadow_likelihood"])
    ground = float(base["persistent_ground_feature_likelihood"])

    clauses = {
        "straightness": straightness >= STRICT_STRAIGHTNESS_MIN,
        "radiometric": radiometric >= STRICT_RADIOMETRIC_MIN,
        "screen_locked": screen_locked >= STRICT_SCREEN_LOCKED_MIN,
        "non_persistent": persistence < STRICT_PERSISTENCE_MAX,
        "not_terrain_shadow": terrain_shadow < STRICT_TERRAIN_SHADOW_MAX,
        "not_ground_feature": ground < STRICT_GROUND_FEATURE_MAX,
        "no_track_line_overlap": track_line_overlap < STRICT_OVERLAP_SUPPRESS,
        "no_ui_overlay_overlap": ui_overlay_overlap < STRICT_OVERLAP_SUPPRESS,
    }

    if all(clauses.values()):
        decision = "probable_tile_seam"
    elif track_line_overlap >= STRICT_OVERLAP_SUPPRESS:
        decision = "probable_track_line"
    elif ui_overlay_overlap >= STRICT_OVERLAP_SUPPRESS:
        decision = "probable_ui_overlay"
    else:
        decision = "indeterminate"

    return {**base, "decision": decision, "strict_clauses": clauses, "screen_locked_score": round(screen_locked, 4)}


def calibrate_strict(candidates_csv: str) -> Dict[str, Any]:
    """L5 calibration using the strict AND-gate. Emits an explicit finding when
    screen_locked_score is absent/zero across all candidates (the gate is then
    inert pending a screen-lock feature extractor)."""
    candidates = load_candidates(candidates_csv)
    scored = [classify_candidate_strict(row) for row in candidates]
    metrics = summarize(scored)
    findings: list[dict[str, Any]] = []
    if not candidates:
        findings.append({"severity": "warning", "detail": "no tile seam/shadow calibration candidates found"})
    elif all(row.get("screen_locked_score", 0.0) <= 0.0 for row in scored):
        findings.append({
            "severity": "warning",
            "detail": "strict L5 gate is inert: screen_locked_score is 0.0 for all candidates "
                      "(no screen-lock feature extractor yet); no tile seams can be promoted under strict rules",
        })
    return LayerCalibrationResult(
        layer="L5_tile_seam_shadow",
        status="READY" if candidates else "MISSING",
        metrics=metrics,
        thresholds={
            "mode": "strict_and_gate",
            "straightness_min": STRICT_STRAIGHTNESS_MIN,
            "radiometric_delta_min": STRICT_RADIOMETRIC_MIN,
            "screen_locked_score_min": STRICT_SCREEN_LOCKED_MIN,
            "multi_date_persistence_max": STRICT_PERSISTENCE_MAX,
            "terrain_shadow_max": STRICT_TERRAIN_SHADOW_MAX,
            "ground_feature_max": STRICT_GROUND_FEATURE_MAX,
            "overlap_suppress": STRICT_OVERLAP_SUPPRESS,
            "note": "conjunctive spec gate; inert until a screen_locked_score feature extractor exists",
        },
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate SATIM L5 tile seam/cloud-shadow discrimination")
    parser.add_argument("--candidates-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.candidates_csv))


if __name__ == "__main__":
    main()
