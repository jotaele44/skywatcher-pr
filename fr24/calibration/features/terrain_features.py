"""L3 terrain-continuity features for SATIM synthetic boundary candidates."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev
from typing import Any, Mapping

from .boundary_geometry import as_float, clamp01


@dataclass(frozen=True)
class TerrainFeatures:
    terrain_crossing: float
    terrain_variance: float
    boundary_deviation: float


def score_terrain_crossing(terrain_variance: float, boundary_deviation: float) -> float:
    """High score when terrain changes while the candidate remains straight."""
    variance_score = clamp01(terrain_variance)
    straight_boundary_score = clamp01(1.0 - boundary_deviation)
    return clamp01(0.65 * variance_score + 0.35 * straight_boundary_score)


def parse_profile(raw: str) -> list[float]:
    values: list[float] = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if token:
            values.append(float(token))
    return values


def compute_terrain_features(row: Mapping[str, Any]) -> TerrainFeatures:
    if "terrain_crossing" in row:
        return TerrainFeatures(
            terrain_crossing=clamp01(as_float(row.get("terrain_crossing"))),
            terrain_variance=clamp01(as_float(row.get("terrain_variance"))),
            boundary_deviation=clamp01(as_float(row.get("boundary_deviation"))),
        )

    profile_raw = str(row.get("terrain_profile", "") or "").strip()
    if profile_raw:
        profile = parse_profile(profile_raw)
        terrain_variance = clamp01(pstdev(profile) / 100.0) if len(profile) > 1 else 0.0
    else:
        terrain_variance = clamp01(as_float(row.get("terrain_variance"), as_float(row.get("dem_variance"))))

    boundary_deviation = clamp01(as_float(row.get("boundary_deviation"), 1.0 - as_float(row.get("straightness"), as_float(row.get("straight_boundary_score")))))

    if "dem_hillshade_alignment" in row:
        # A high hillshade alignment means terrain may explain the boundary, so it
        # should reduce terrain-crossing evidence.
        hillshade_alignment = clamp01(as_float(row.get("dem_hillshade_alignment")))
        terrain_crossing = clamp01(score_terrain_crossing(terrain_variance, boundary_deviation) * (1.0 - hillshade_alignment))
    else:
        terrain_crossing = score_terrain_crossing(terrain_variance, boundary_deviation)

    return TerrainFeatures(
        terrain_crossing=terrain_crossing,
        terrain_variance=terrain_variance,
        boundary_deviation=boundary_deviation,
    )
