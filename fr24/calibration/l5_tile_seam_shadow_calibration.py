"""L5 SATIM calibration: imagery-seam observation and causal-origin controls.

The legacy weighted ``tile_seam_likelihood`` score is retained for calibration
continuity, but it is an observation/artifact heuristic only. Causal origin is
adjudicated by explicit coordinate-behavior and binding gates so a source
mosaic cutline, renderer tile edge, viewport artifact, shadow, or physical
ground feature cannot be silently collapsed into one class.
"""
from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .models import LayerCalibrationResult, write_json

DECISIONS = {
    "probable_tile_seam",  # legacy weighted observation label only
    "probable_imagery_seam_unresolved_origin",
    "probable_source_mosaic_cutline",
    "probable_display_tile_edge",
    "probable_viewport_artifact",
    "probable_cloud_shadow",
    "probable_terrain_shadow",
    "probable_ground_feature",
    "ground_feature_candidate",
    "explainable_infrastructure",
    "probable_track_line",
    "probable_ui_overlay",
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
    """Return how strongly visible context explains orthogonal geometry."""
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
    """Count visual seam signals excluding the weak right-angle prior."""
    signals = [
        straight >= 0.55,
        radiometric >= 0.55,
        texture >= 0.55,
        rectangular >= 0.55,
        persistence <= 0.35,
        terrain <= 0.35,
    ]
    return sum(1 for item in signals if item)


def classify_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    """Legacy weighted visual-artifact classifier.

    ``probable_tile_seam`` is retained for backwards compatibility but is not a
    causal renderer-tile identity. ``resolved_origin`` is always UNRESOLVED in
    this weighted path; use :func:`classify_candidate_strict` for origin gates.
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

    return {
        **scores,
        "decision": decision,
        "decision_semantics": "LEGACY_VISUAL_HEURISTIC_ONLY",
        "resolved_origin": "UNRESOLVED",
    }


def load_candidates(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    counts = {decision: 0 for decision in DECISIONS}
    for row in rows:
        decision = str(row.get("decision", "indeterminate"))
        counts[decision] = counts.get(decision, 0) + 1
    return {"candidate_count": len(rows), "decision_counts": counts}


def calibrate(candidates_csv: str) -> dict[str, Any]:
    candidates = load_candidates(candidates_csv)
    scored = [classify_candidate(row) for row in candidates]
    metrics = summarize(scored)
    findings = []
    if not candidates:
        findings.append({"severity": "warning", "detail": "no imagery-seam/shadow calibration candidates found"})
    status = "READY" if candidates else "MISSING"
    return LayerCalibrationResult(
        layer="L5_tile_seam_shadow",
        status=status,
        metrics=metrics,
        thresholds={
            "promotion_min_likelihood": 0.55,
            "weighted_path_semantics": "visual seam/artifact heuristic only; never causal origin identity",
            "orthogonal_artifact_rule": "right angles are weak priors requiring at least two corroborating seam signals",
            "legacy_tile_seam_rule": "straight/rectangular boundary + radiometric or texture discontinuity + non-persistence + no terrain alignment",
            "context_suppressors": "roads, runways, reservoirs, utility plants, quarries, parcels, and buildings suppress seam promotion",
            "ground_feature_rule": "multi-date persistence + infrastructure/landcover alignment + low cloud/shadow intersection",
        },
        findings=findings,
    ).to_dict()


# ---------------------------------------------------------------------------
# Strict origin firewall (docs/SATIM_TRACK_LINE_VS_TILE_SEAM_RULES.md)
# ---------------------------------------------------------------------------
STRICT_STRAIGHTNESS_MIN = 0.85
STRICT_RADIOMETRIC_MIN = 0.55
STRICT_SCREEN_LOCKED_MIN = 0.70
STRICT_SCREEN_LOCKED_MAX_FOR_TILE = 0.55
STRICT_GROUND_FIXED_MIN = 0.70
STRICT_GROUND_FIXED_MAX_FOR_VIEWPORT = 0.35
STRICT_PROVIDER_TILE_GRID_MIN = 0.80
STRICT_PROVIDER_TILE_GRID_MAX_FOR_MOSAIC = 0.35
STRICT_ADJACENT_ZOOM_PERSISTENCE_MIN = 0.65
STRICT_SOURCE_MOSAIC_METADATA_MIN = 0.90
STRICT_INDEPENDENT_GROUND_BINDING_MIN = 0.90
STRICT_TERRAIN_SHADOW_MAX = 0.55
STRICT_GROUND_FEATURE_MAX = 0.55
STRICT_OVERLAP_SUPPRESS = 0.55


def classify_candidate_strict(row: Mapping[str, Any]) -> dict[str, Any]:
    """Origin-aware conjunctive gate.

    The strict path first establishes a visual imagery-seam observation, then
    adjudicates coordinate behavior and causal origin. Screen lock is a
    viewport-artifact signal, not renderer-tile identity.

    Required origin-specific evidence:
    - DISPLAY_TILE_EDGE: provider tile-grid binding;
    - SOURCE_MOSAIC_CUTLINE: ground-fixed + adjacent-zoom persistence + not
      provider-grid-bound, with PASS reserved for source-mosaic metadata;
    - PHYSICAL_GROUND_FEATURE: independent physical-ground binding.
    """
    base = classify_candidate(row)
    straightness = score(row, "straightness", "straight_boundary_score", "straight_edge_score")
    radiometric = score(row, "radiometric_delta", "radiometric_discontinuity_score", "color_discontinuity_score")
    screen_locked = score(row, "screen_locked_score")
    ground_fixed = score(row, "ground_fixed_score", "ground_fixed_under_pan_score")
    provider_grid = score(row, "provider_tile_grid_binding_score", "tile_grid_binding_score")
    adjacent_zoom = score(row, "adjacent_zoom_ground_persistence_score", "persists_across_adjacent_zoom_levels_score")
    mosaic_metadata = score(row, "source_mosaic_metadata_binding_score")
    independent_ground_binding = score(row, "independent_ground_feature_binding_score")
    track_line_overlap = score(row, "track_line_overlap")
    ui_overlay_overlap = score(row, "ui_overlay_overlap")
    terrain_shadow = float(base["terrain_shadow_likelihood"])
    ground_likelihood = float(base["persistent_ground_feature_likelihood"])

    observation_clauses = {
        "straightness": straightness >= STRICT_STRAIGHTNESS_MIN,
        "radiometric": radiometric >= STRICT_RADIOMETRIC_MIN,
        "not_terrain_shadow": terrain_shadow < STRICT_TERRAIN_SHADOW_MAX,
        "no_track_line_overlap": track_line_overlap < STRICT_OVERLAP_SUPPRESS,
        "no_ui_overlay_overlap": ui_overlay_overlap < STRICT_OVERLAP_SUPPRESS,
    }
    imagery_seam_observed = all(observation_clauses.values())

    origin_state = "UNRESOLVED"
    origin = "UNRESOLVED"
    origin_gates: dict[str, bool] = {}

    if track_line_overlap >= STRICT_OVERLAP_SUPPRESS:
        decision = "probable_track_line"
    elif ui_overlay_overlap >= STRICT_OVERLAP_SUPPRESS:
        decision = "probable_ui_overlay"
    elif independent_ground_binding >= STRICT_INDEPENDENT_GROUND_BINDING_MIN:
        decision = "probable_ground_feature"
        origin = "PHYSICAL_GROUND_FEATURE"
        origin_state = "PASS"
        origin_gates = {"independent_ground_feature_binding": True}
    elif not imagery_seam_observed:
        decision = "indeterminate"
    elif (
        screen_locked >= STRICT_SCREEN_LOCKED_MIN
        and ground_fixed <= STRICT_GROUND_FIXED_MAX_FOR_VIEWPORT
    ):
        decision = "probable_viewport_artifact"
        origin = "VIEWPORT_COMPOSITING_ARTIFACT"
        origin_state = "PASS"
        origin_gates = {
            "screen_fixed_under_pan": True,
            "not_ground_fixed_under_pan": True,
        }
    elif (
        provider_grid >= STRICT_PROVIDER_TILE_GRID_MIN
        and screen_locked < STRICT_SCREEN_LOCKED_MAX_FOR_TILE
        and ground_likelihood < STRICT_GROUND_FEATURE_MAX
    ):
        decision = "probable_display_tile_edge"
        origin = "DISPLAY_TILE_EDGE"
        origin_state = "PASS"
        origin_gates = {
            "provider_tile_grid_binding": True,
            "not_screen_fixed": True,
            "not_ground_feature": True,
        }
    elif (
        ground_fixed >= STRICT_GROUND_FIXED_MIN
        and adjacent_zoom >= STRICT_ADJACENT_ZOOM_PERSISTENCE_MIN
        and provider_grid <= STRICT_PROVIDER_TILE_GRID_MAX_FOR_MOSAIC
        and ground_likelihood < STRICT_GROUND_FEATURE_MAX
    ):
        decision = "probable_source_mosaic_cutline"
        origin = "SOURCE_MOSAIC_CUTLINE"
        origin_state = "PASS" if mosaic_metadata >= STRICT_SOURCE_MOSAIC_METADATA_MIN else "PROVISIONAL"
        origin_gates = {
            "ground_fixed_under_pan": True,
            "adjacent_zoom_ground_persistence": True,
            "not_provider_tile_grid_bound": True,
            "not_ground_feature": True,
            "source_mosaic_metadata_binding": mosaic_metadata >= STRICT_SOURCE_MOSAIC_METADATA_MIN,
        }
    else:
        decision = "probable_imagery_seam_unresolved_origin"
        origin_gates = {
            "provider_tile_grid_binding": provider_grid >= STRICT_PROVIDER_TILE_GRID_MIN,
            "screen_fixed_under_pan": screen_locked >= STRICT_SCREEN_LOCKED_MIN,
            "ground_fixed_under_pan": ground_fixed >= STRICT_GROUND_FIXED_MIN,
            "adjacent_zoom_ground_persistence": adjacent_zoom >= STRICT_ADJACENT_ZOOM_PERSISTENCE_MIN,
            "independent_ground_feature_binding": independent_ground_binding >= STRICT_INDEPENDENT_GROUND_BINDING_MIN,
        }

    return {
        **base,
        "decision": decision,
        "decision_semantics": "ORIGIN_AWARE_STRICT_GATE",
        "imagery_seam_observed": imagery_seam_observed,
        "observation_clauses": observation_clauses,
        "resolved_origin": origin if origin_state == "PASS" else "UNRESOLVED",
        "leading_origin_candidate": origin,
        "origin_state": origin_state,
        "origin_gates": origin_gates,
        "screen_locked_score": round(screen_locked, 4),
        "ground_fixed_score": round(ground_fixed, 4),
        "provider_tile_grid_binding_score": round(provider_grid, 4),
        "adjacent_zoom_ground_persistence_score": round(adjacent_zoom, 4),
        "source_mosaic_metadata_binding_score": round(mosaic_metadata, 4),
        "independent_ground_feature_binding_score": round(independent_ground_binding, 4),
    }


def calibrate_strict(candidates_csv: str) -> dict[str, Any]:
    """L5 calibration using the origin-aware strict gate."""
    candidates = load_candidates(candidates_csv)
    scored = [classify_candidate_strict(row) for row in candidates]
    metrics = summarize(scored)
    findings: list[dict[str, Any]] = []
    if not candidates:
        findings.append({"severity": "warning", "detail": "no imagery-seam/shadow calibration candidates found"})
    elif all(
        row.get("screen_locked_score", 0.0) <= 0.0
        and row.get("ground_fixed_score", 0.0) <= 0.0
        and row.get("provider_tile_grid_binding_score", 0.0) <= 0.0
        and row.get("independent_ground_feature_binding_score", 0.0) <= 0.0
        for row in scored
    ):
        findings.append({
            "severity": "warning",
            "detail": "strict origin firewall lacks coordinate-behavior/binding features; imagery seams may be observed but causal origin remains unresolved",
        })
    return LayerCalibrationResult(
        layer="L5_tile_seam_shadow",
        status="READY" if candidates else "MISSING",
        metrics=metrics,
        thresholds={
            "mode": "origin_aware_strict_gate",
            "straightness_min": STRICT_STRAIGHTNESS_MIN,
            "radiometric_delta_min": STRICT_RADIOMETRIC_MIN,
            "screen_locked_viewport_min": STRICT_SCREEN_LOCKED_MIN,
            "screen_locked_tile_max": STRICT_SCREEN_LOCKED_MAX_FOR_TILE,
            "ground_fixed_min": STRICT_GROUND_FIXED_MIN,
            "provider_tile_grid_binding_min": STRICT_PROVIDER_TILE_GRID_MIN,
            "adjacent_zoom_ground_persistence_min": STRICT_ADJACENT_ZOOM_PERSISTENCE_MIN,
            "source_mosaic_metadata_binding_min": STRICT_SOURCE_MOSAIC_METADATA_MIN,
            "independent_ground_feature_binding_min": STRICT_INDEPENDENT_GROUND_BINDING_MIN,
            "terrain_shadow_max": STRICT_TERRAIN_SHADOW_MAX,
            "ground_feature_max": STRICT_GROUND_FEATURE_MAX,
            "overlap_suppress": STRICT_OVERLAP_SUPPRESS,
            "note": "screen lock identifies viewport-relative behavior; provider tile-grid binding is required for DISPLAY_TILE_EDGE",
        },
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate SATIM L5 imagery-seam/cloud-shadow discrimination")
    parser.add_argument("--candidates-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.candidates_csv))


if __name__ == "__main__":
    main()
