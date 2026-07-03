"""SATIM tile seam artifact classifier.

This module provides a small deterministic classifier for calibration fixtures where
screen-captured basemap imagery shows tonal discontinuities that are more consistent
with map-provider tile stitching than with physical ground features.

The rules are intentionally conservative: they only promote a case to
``TILE_SEAM_PROBABLE`` when seam behavior crosses unrelated object classes and does
not follow plausible real-world geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


TILE_SEAM_PROBABLE = "TILE_SEAM_PROBABLE"
TILE_SEAM_CANDIDATE = "TILE_SEAM_CANDIDATE"
TILE_SEAM_INSUFFICIENT = "TILE_SEAM_INSUFFICIENT"


@dataclass(frozen=True)
class TileSeamEvidence:
    """Boolean evidence flags for tile-seam calibration.

    The fields are derived metadata only. Do not store raw coordinates, EXIF, or
    identifiable property imagery in public calibration fixtures.
    """

    crosses_landcover_classes: bool = False
    persists_across_zoomed_frames: bool = False
    roof_or_object_texture_split: bool = False
    object_anchors_consistent: bool = False
    follows_physical_geometry: bool = False
    shadow_explanation_plausible: bool = False
    raw_coordinate_released: bool = False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def evidence_from_mapping(row: Mapping[str, object]) -> TileSeamEvidence:
    """Build ``TileSeamEvidence`` from a CSV/JSON-like row."""

    return TileSeamEvidence(
        crosses_landcover_classes=_truthy(row.get("crosses_landcover_classes", False)),
        persists_across_zoomed_frames=_truthy(row.get("persists_across_zoomed_frames", False)),
        roof_or_object_texture_split=_truthy(row.get("roof_or_object_texture_split", False)),
        object_anchors_consistent=_truthy(row.get("object_anchors_consistent", False)),
        follows_physical_geometry=_truthy(row.get("follows_physical_geometry", False)),
        shadow_explanation_plausible=_truthy(row.get("shadow_explanation_plausible", False)),
        raw_coordinate_released=_truthy(row.get("raw_coordinate_released", False)),
    )


def classify_tile_seam(evidence: TileSeamEvidence) -> dict[str, object]:
    """Classify a probable basemap tile seam from derived evidence flags.

    Returns a stable dictionary so tests and downstream ledgers can serialize the
    decision without importing enum types.
    """

    positive_flags = [
        evidence.crosses_landcover_classes,
        evidence.persists_across_zoomed_frames,
        evidence.roof_or_object_texture_split,
        evidence.object_anchors_consistent,
    ]
    positive_score = sum(1 for flag in positive_flags if flag)

    contradiction_score = sum(
        1
        for flag in [
            evidence.follows_physical_geometry,
            evidence.shadow_explanation_plausible,
            evidence.raw_coordinate_released,
        ]
        if flag
    )

    if evidence.raw_coordinate_released:
        return {
            "label": TILE_SEAM_INSUFFICIENT,
            "artifact_confidence": "HOLD",
            "ground_feature_confidence": "UNKNOWN",
            "privacy_status": "BLOCK_RAW_COORDINATE_RELEASE",
            "positive_score": positive_score,
            "contradiction_score": contradiction_score,
        }

    if positive_score >= 3 and contradiction_score == 0:
        label = TILE_SEAM_PROBABLE
        artifact_confidence = "MEDIUM_HIGH"
        ground_feature_confidence = "LOW"
    elif positive_score >= 2:
        label = TILE_SEAM_CANDIDATE
        artifact_confidence = "MEDIUM"
        ground_feature_confidence = "LOW_TO_UNKNOWN"
    else:
        label = TILE_SEAM_INSUFFICIENT
        artifact_confidence = "LOW"
        ground_feature_confidence = "UNKNOWN"

    return {
        "label": label,
        "artifact_confidence": artifact_confidence,
        "ground_feature_confidence": ground_feature_confidence,
        "privacy_status": "DERIVED_FIXTURE_ONLY",
        "positive_score": positive_score,
        "contradiction_score": contradiction_score,
    }


def classify_many(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Classify multiple CSV/JSON-style rows."""

    return [classify_tile_seam(evidence_from_mapping(row)) for row in rows]
