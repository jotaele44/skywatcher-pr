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
    "indeterminate",
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def classify_candidate(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify one candidate from normalized feature scores.

    Expected columns are booleans or 0..1 numeric scores:
    straight_boundary_score, radiometric_discontinuity_score,
    cloud_mask_intersection, shadow_mask_intersection, dem_hillshade_alignment,
    multi_date_persistence, infrastructure_alignment.
    """
    straight = float(row.get("straight_boundary_score", 0) or 0)
    radiometric = float(row.get("radiometric_discontinuity_score", 0) or 0)
    cloud = float(row.get("cloud_mask_intersection", 0) or 0)
    shadow = float(row.get("shadow_mask_intersection", 0) or 0)
    terrain = float(row.get("dem_hillshade_alignment", 0) or 0)
    persistence = float(row.get("multi_date_persistence", 0) or 0)
    infrastructure = float(row.get("infrastructure_alignment", 0) or 0)

    tile = clamp01((straight + radiometric + (1.0 - persistence) + (1.0 - terrain)) / 4.0)
    cloud_shadow = clamp01(max(cloud, shadow) * max(radiometric, 0.1))
    terrain_shadow = clamp01(terrain * max(shadow, radiometric))
    ground = clamp01((persistence + infrastructure + (1.0 - max(cloud, shadow))) / 3.0)

    scores = {
        "tile_seam_likelihood": tile,
        "cloud_shadow_likelihood": cloud_shadow,
        "terrain_shadow_likelihood": terrain_shadow,
        "persistent_ground_feature_likelihood": ground,
    }
    best_key = max(scores, key=scores.get)
    if scores[best_key] < 0.55:
        decision = "indeterminate"
    elif best_key == "tile_seam_likelihood":
        decision = "probable_tile_seam"
    elif best_key == "cloud_shadow_likelihood":
        decision = "probable_cloud_shadow"
    elif best_key == "terrain_shadow_likelihood":
        decision = "probable_terrain_shadow"
    else:
        decision = "probable_ground_feature"
    return {**scores, "decision": decision}


def load_candidates(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(results)
    counts = {decision: 0 for decision in DECISIONS}
    for row in rows:
        counts[str(row.get("decision", "indeterminate"))] = counts.get(str(row.get("decision", "indeterminate")), 0) + 1
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
            "tile_seam_rule": "straight boundary + radiometric discontinuity + non-persistence + no terrain alignment",
            "ground_feature_rule": "multi-date persistence + infrastructure/landcover alignment + low cloud/shadow intersection",
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
