"""L2 infrastructure-alignment features for SATIM synthetic boundary candidates.

This module intentionally returns weighted alignment scores instead of binary
rejections. Roads, buildings, airports, ports, parcels, and industrial sites can
all generate strong 90-degree geometry; a classifier should downweight synthetic
boundary likelihood when alignment is strong, not discard candidates blindly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .boundary_geometry import as_float, clamp01


@dataclass(frozen=True)
class InfrastructureFeatures:
    road_alignment: float
    building_alignment: float
    airport_alignment: float
    parcel_alignment: float
    infrastructure_rejection: float


def max_score(*values: float) -> float:
    return clamp01(max(values) if values else 0.0)


def aggregate_infrastructure_rejection(
    road_alignment: float,
    building_alignment: float,
    airport_alignment: float,
    parcel_alignment: float,
) -> float:
    """Return confidence that infrastructure explains the boundary."""
    return clamp01(
        0.30 * road_alignment
        + 0.25 * building_alignment
        + 0.25 * airport_alignment
        + 0.20 * parcel_alignment
    )


def load_airport_footprint_rows(paths: Iterable[str | Path]) -> list[dict[str, str]]:
    """Load airport footprint registries for downstream spatial scoring.

    The classifier can operate without geometry. When geocoded registries exist,
    callers can compute candidate-specific overlap/alignment externally and pass
    the resulting ``airport_alignment`` score into ``compute_infrastructure_features``.
    """
    rows: list[dict[str, str]] = []
    for path_value in paths:
        path = Path(path_value)
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(dict(row) for row in csv.DictReader(handle))
    return rows


def compute_airport_alignment_from_overlap(overlap_fraction: float, angle_similarity: float = 1.0) -> float:
    """Score candidate alignment to known airport infrastructure.

    ``overlap_fraction`` and ``angle_similarity`` should already be normalized by
    the caller's geospatial engine.
    """
    return clamp01(0.70 * clamp01(overlap_fraction) + 0.30 * clamp01(angle_similarity))


def compute_infrastructure_features(row: Mapping[str, Any]) -> InfrastructureFeatures:
    road_alignment = clamp01(as_float(row.get("road_alignment"), as_float(row.get("road_alignment_score"))))
    building_alignment = clamp01(as_float(row.get("building_alignment"), as_float(row.get("building_alignment_score"))))
    airport_alignment = clamp01(as_float(row.get("airport_alignment"), as_float(row.get("airport_alignment_score"))))
    parcel_alignment = clamp01(as_float(row.get("parcel_alignment"), as_float(row.get("parcel_alignment_score"))))

    legacy_alignment = row.get("infrastructure_alignment")
    if legacy_alignment not in (None, ""):
        legacy = clamp01(as_float(legacy_alignment))
        road_alignment = max_score(road_alignment, legacy)

    rejection = aggregate_infrastructure_rejection(
        road_alignment=road_alignment,
        building_alignment=building_alignment,
        airport_alignment=airport_alignment,
        parcel_alignment=parcel_alignment,
    )

    return InfrastructureFeatures(
        road_alignment=road_alignment,
        building_alignment=building_alignment,
        airport_alignment=airport_alignment,
        parcel_alignment=parcel_alignment,
        infrastructure_rejection=rejection,
    )
