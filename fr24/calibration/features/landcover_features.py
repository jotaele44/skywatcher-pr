"""L4 landcover persistence and coastal-crossing features for SATIM candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .boundary_geometry import as_float, clamp01

COASTAL_CLASSES = {"beach", "coast", "reef", "water", "ocean", "wetland", "mangrove"}


@dataclass(frozen=True)
class LandcoverFeatures:
    landcover_persistence: float
    coastal_crossing_score: float
    landcover_class_count: int
    boundary_continuity: float


def parse_classes(raw: str) -> list[str]:
    return [token.strip().lower() for token in raw.replace(";", ",").split(",") if token.strip()]


def score_landcover_persistence(class_count: int, boundary_continuity: float) -> float:
    class_score = clamp01(max(0, class_count - 1) / 4.0)
    return clamp01(0.55 * class_score + 0.45 * boundary_continuity)


def score_coastal_crossing(classes: list[str], boundary_continuity: float) -> float:
    if not classes:
        return 0.0
    coastal_hits = sum(1 for item in classes if item in COASTAL_CLASSES)
    land_hits = len(classes) - coastal_hits
    if coastal_hits == 0 or land_hits == 0:
        return 0.0
    return clamp01((coastal_hits / len(classes)) * 0.5 + boundary_continuity * 0.5)


def compute_landcover_features(row: Mapping[str, Any]) -> LandcoverFeatures:
    if "landcover_persistence" in row:
        return LandcoverFeatures(
            landcover_persistence=clamp01(as_float(row.get("landcover_persistence"))),
            coastal_crossing_score=clamp01(as_float(row.get("coastal_crossing_score"))),
            landcover_class_count=int(as_float(row.get("landcover_class_count"), 0)),
            boundary_continuity=clamp01(as_float(row.get("boundary_continuity"), as_float(row.get("straightness"), 0))),
        )

    classes = parse_classes(str(row.get("landcover_classes", "") or ""))
    class_count = len(set(classes)) if classes else int(as_float(row.get("number_of_landcover_classes_crossed"), 0))
    boundary_continuity = clamp01(as_float(row.get("boundary_continuity"), as_float(row.get("straightness"), as_float(row.get("straight_boundary_score")))))
    persistence = score_landcover_persistence(class_count, boundary_continuity)
    coastal = clamp01(as_float(row.get("coastal_crossing_score"), score_coastal_crossing(classes, boundary_continuity)))

    return LandcoverFeatures(
        landcover_persistence=persistence,
        coastal_crossing_score=coastal,
        landcover_class_count=class_count,
        boundary_continuity=boundary_continuity,
    )
