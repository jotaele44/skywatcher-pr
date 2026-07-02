"""SATIM Phase 2 raster candidate extraction stub.

This module converts image-derived boundary detections into the Phase 1
``satim.visual_ledger.v1`` candidate contract. The implementation is intentionally
lightweight and dependency-optional: callers may pass precomputed image metrics,
while future raster backends can replace ``detect_raster_candidates`` with OpenCV,
scikit-image, or GDAL-driven extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .satim_candidate_extraction import DEFAULT_FEATURE_SCORES, normalize_candidate


@dataclass(frozen=True)
class RasterExtractionConfig:
    """Thresholds used by the conservative Phase 2 raster extraction contract."""

    straightness_min: float = 0.85
    radiometric_delta_min: float = 0.55
    min_boundary_length_px: float = 24.0
    default_candidate_kind: str = "linear_boundary"


def _score(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def candidate_from_detection(
    detection: Mapping[str, Any],
    *,
    source_image_id: str,
    source_uri: str,
    capture_datetime_utc: str,
    aoi_id: str,
    visual_id_prefix: str = "SATIM-VIS",
    sequence: int = 1,
) -> dict[str, Any]:
    """Convert one raster detection into a SATIM visual-ledger row.

    ``detection`` is expected to contain geometry plus optional feature scores.
    This function performs no image IO; it is the stable adapter contract for
    future raster extractors.
    """
    feature_scores = dict(DEFAULT_FEATURE_SCORES)
    for key in feature_scores:
        if key in detection:
            feature_scores[key] = _score(detection[key])

    visual_id = str(detection.get("visual_id") or f"{visual_id_prefix}-{source_image_id}_{sequence:04d}")
    return normalize_candidate({
        "visual_id": visual_id,
        "source_image_id": source_image_id,
        "source_uri": source_uri,
        "capture_datetime_utc": capture_datetime_utc,
        "imagery_provider": detection.get("imagery_provider"),
        "imagery_epoch": detection.get("imagery_epoch"),
        "aoi_id": aoi_id,
        "municipality": detection.get("municipality"),
        "candidate_kind": detection.get("candidate_kind", "linear_boundary"),
        "geometry": detection["geometry"],
        "feature_scores": feature_scores,
        "classification": detection.get("classification", "indeterminate"),
        "confidence": detection.get("confidence", max(feature_scores["straightness"], feature_scores["radiometric_delta"])),
        "review_state": detection.get("review_state", "unreviewed"),
        "contradiction_flags": detection.get("contradiction_flags") or [],
        "cross_source_refs": detection.get("cross_source_refs") or [],
    })


def detect_raster_candidates(
    detections: Iterable[Mapping[str, Any]],
    *,
    source_image_id: str,
    source_uri: str,
    capture_datetime_utc: str,
    aoi_id: str,
    config: RasterExtractionConfig | None = None,
) -> list[dict[str, Any]]:
    """Filter precomputed detections and emit visual-ledger candidate rows.

    Future implementation should replace the iterable with true raster-derived
    detections. The current function is still useful for fixture-driven tests and
    locks down the Phase 2 output contract.
    """
    cfg = config or RasterExtractionConfig()
    rows: list[dict[str, Any]] = []
    for index, detection in enumerate(detections, start=1):
        length_px = float(detection.get("boundary_length_px", detection.get("boundary_length", 0.0)) or 0.0)
        straightness = _score(detection.get("straightness", detection.get("straight_boundary_score")))
        radiometric = _score(detection.get("radiometric_delta", detection.get("radiometric_discontinuity_score")))
        if length_px < cfg.min_boundary_length_px:
            continue
        if straightness < cfg.straightness_min and radiometric < cfg.radiometric_delta_min:
            continue
        normalized = candidate_from_detection(
            {"candidate_kind": cfg.default_candidate_kind, **detection},
            source_image_id=source_image_id,
            source_uri=source_uri,
            capture_datetime_utc=capture_datetime_utc,
            aoi_id=aoi_id,
            sequence=index,
        )
        rows.append(normalized)
    return rows
