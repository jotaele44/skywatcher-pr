"""L5 SATIM synthetic boundary classifier.

Pipeline alignment:
L0 candidate extraction -> geometry features
L1 radiometric evidence
L2 infrastructure alignment scores
L3 terrain continuity
L4 landcover/coastal persistence
L5 weighted synthetic-boundary classification

The classifier treats infrastructure as a weighted alignment penalty rather than
as a hard rejection layer. This prevents brittle rule-heavy behavior in airports,
ports, industrial zones, and urban grids.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from .features import (
    compute_boundary_geometry_features,
    compute_infrastructure_features,
    compute_landcover_features,
    compute_radiometric_features,
    compute_terrain_features,
)
from .features.boundary_geometry import clamp01
from .models import LayerCalibrationResult, write_json

PROMOTION_THRESHOLD = 0.55

WEIGHTS = {
    "straightness": 0.20,
    "radiometric_delta": 0.30,
    "terrain_crossing": 0.15,
    "landcover_persistence": 0.20,
    "infrastructure_rejection": 0.10,
    "orthogonality": 0.05,
    "coastal_crossing_score": 0.05,
}

ALIGNMENT_FIELDS = {
    "road_alignment",
    "building_alignment",
    "airport_alignment",
    "parcel_alignment",
}

DECISIONS = {
    "probable_tile_seam",
    "probable_ground_feature",
    "probable_cloud_shadow",
    "probable_terrain_shadow",
    "indeterminate",
}


def extract_candidate_features(row: Mapping[str, Any]) -> Dict[str, float]:
    """Generate normalized L0-L4 features for one candidate boundary."""
    geometry = compute_boundary_geometry_features(row)
    radiometric = compute_radiometric_features(row)
    infrastructure = compute_infrastructure_features(row)
    terrain = compute_terrain_features(row)
    landcover = compute_landcover_features(row)

    return {
        "straightness": geometry.straightness,
        "orthogonality": geometry.orthogonality,
        "radiometric_delta": radiometric.radiometric_delta,
        "terrain_crossing": terrain.terrain_crossing,
        "landcover_persistence": landcover.landcover_persistence,
        "coastal_crossing_score": landcover.coastal_crossing_score,
        "road_alignment": infrastructure.road_alignment,
        "building_alignment": infrastructure.building_alignment,
        "airport_alignment": infrastructure.airport_alignment,
        "parcel_alignment": infrastructure.parcel_alignment,
        "infrastructure_rejection": infrastructure.infrastructure_rejection,
    }


def infrastructure_explanation_penalty(features: Mapping[str, float]) -> float:
    """Return how strongly real-world infrastructure explains the boundary."""
    return clamp01(float(features.get("infrastructure_rejection", 0.0) or 0.0))


def classify_synthetic_boundary(features: Mapping[str, float]) -> Dict[str, Any]:
    """Classify using weighted features without hard infrastructure rejection."""
    straightness = clamp01(float(features.get("straightness", 0.0) or 0.0))
    radiometric_delta = clamp01(float(features.get("radiometric_delta", 0.0) or 0.0))
    terrain_crossing = clamp01(float(features.get("terrain_crossing", 0.0) or 0.0))
    landcover_persistence = clamp01(float(features.get("landcover_persistence", 0.0) or 0.0))
    coastal_crossing = clamp01(float(features.get("coastal_crossing_score", 0.0) or 0.0))
    orthogonality = clamp01(float(features.get("orthogonality", 0.0) or 0.0))
    infrastructure_penalty = infrastructure_explanation_penalty(features)

    positive = clamp01(
        WEIGHTS["straightness"] * straightness
        + WEIGHTS["radiometric_delta"] * radiometric_delta
        + WEIGHTS["terrain_crossing"] * terrain_crossing
        + WEIGHTS["landcover_persistence"] * landcover_persistence
        + WEIGHTS["orthogonality"] * orthogonality
        + WEIGHTS["coastal_crossing_score"] * coastal_crossing
    )
    penalty = WEIGHTS["infrastructure_rejection"] * infrastructure_penalty
    tile_seam_likelihood = clamp01(positive - penalty)

    ground_feature_likelihood = clamp01(
        0.55 * infrastructure_penalty
        + 0.25 * max(clamp01(float(features.get(field, 0.0) or 0.0)) for field in ALIGNMENT_FIELDS)
        + 0.20 * (1.0 - radiometric_delta)
    )
    cloud_shadow_likelihood = clamp01(
        max(
            float(features.get("cloud_mask_intersection", 0.0) or 0.0),
            float(features.get("shadow_mask_intersection", 0.0) or 0.0),
        )
        * max(radiometric_delta, 0.1)
    )
    terrain_shadow_likelihood = clamp01(
        clamp01(float(features.get("dem_hillshade_alignment", 0.0) or 0.0))
        * max(radiometric_delta, cloud_shadow_likelihood)
    )

    scores = {
        "tile_seam_likelihood": tile_seam_likelihood,
        "persistent_ground_feature_likelihood": ground_feature_likelihood,
        "cloud_shadow_likelihood": cloud_shadow_likelihood,
        "terrain_shadow_likelihood": terrain_shadow_likelihood,
    }
    best_key = max(scores, key=scores.get)

    if scores[best_key] < PROMOTION_THRESHOLD:
        decision = "indeterminate"
    elif best_key == "tile_seam_likelihood":
        decision = "probable_tile_seam"
    elif best_key == "persistent_ground_feature_likelihood":
        decision = "probable_ground_feature"
    elif best_key == "cloud_shadow_likelihood":
        decision = "probable_cloud_shadow"
    else:
        decision = "probable_terrain_shadow"

    return {
        **scores,
        "classification": decision,
        "decision": decision,
        "confidence": round(scores[best_key], 4),
        "infrastructure_penalty": round(penalty, 4),
        "feature_weights": WEIGHTS,
    }


def classify_candidate(row: Mapping[str, Any]) -> Dict[str, Any]:
    features = extract_candidate_features(row)
    return {**features, **classify_synthetic_boundary({**row, **features})}


def load_candidates(path: str | Path) -> list[dict[str, str]]:
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
        findings.append({"severity": "warning", "detail": "no synthetic boundary candidates found"})
    return LayerCalibrationResult(
        layer="L5_synthetic_boundary",
        status="READY" if candidates else "MISSING",
        metrics=metrics,
        thresholds={
            "promotion_min_likelihood": PROMOTION_THRESHOLD,
            "weights": WEIGHTS,
            "infrastructure_model": "weighted alignment penalty; no hard rejection",
            "tile_seam_rule": "straight + radiometric + terrain/landcover/coastal persistence - infrastructure alignment",
        },
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify SATIM synthetic boundary candidates")
    parser.add_argument("--candidates-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.candidates_csv))


if __name__ == "__main__":
    main()
