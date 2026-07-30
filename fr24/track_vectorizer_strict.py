"""Fail-closed adapter around the FR24 track vectorizer.

The legacy ``vectorize_image`` API intentionally returns ``None`` for both
"no route pixels" and runtime failure. This adapter separates those outcomes so
corpus certification can distinguish a valid negative from a broken extractor.
"""
from __future__ import annotations

from dataclasses import dataclass

from fr24.route_extractor import RouteExtractor
from fr24.track_vectorizer import TrackFeatures, vectorize_candidates


@dataclass(frozen=True)
class VectorizationReceipt:
    status: str
    features: TrackFeatures | None
    error: str | None
    candidate_count: int
    extractor_mode: str


def vectorize_image_receipt(
    image_path: str,
    extractor: RouteExtractor | None = None,
) -> VectorizationReceipt:
    extractor_mode = "provided"
    if extractor is None:
        try:
            from fr24.ui_segmenter import FR24UISegmenter

            extractor = RouteExtractor(FR24UISegmenter(mode="geometric"))
            extractor_mode = "fr24_geometric"
        except Exception as exc:
            try:
                extractor = RouteExtractor()
                extractor_mode = f"default_after_segmenter_error:{type(exc).__name__}"
            except Exception as fallback_exc:
                return VectorizationReceipt(
                    status="failed",
                    features=None,
                    error=(
                        f"extractor_init_failed: {type(exc).__name__}: {exc}; "
                        f"fallback_failed: {type(fallback_exc).__name__}: {fallback_exc}"
                    )[:500],
                    candidate_count=0,
                    extractor_mode="unavailable",
                )

    try:
        candidates = extractor.extract(image_path)
    except Exception as exc:
        return VectorizationReceipt(
            status="failed",
            features=None,
            error=f"extract_failed: {type(exc).__name__}: {exc}"[:500],
            candidate_count=0,
            extractor_mode=extractor_mode,
        )
    if not candidates:
        return VectorizationReceipt(
            status="no_track_detected",
            features=None,
            error=None,
            candidate_count=0,
            extractor_mode=extractor_mode,
        )

    try:
        features = vectorize_candidates(candidates)
    except Exception as exc:
        return VectorizationReceipt(
            status="failed",
            features=None,
            error=f"vectorize_failed: {type(exc).__name__}: {exc}"[:500],
            candidate_count=len(candidates),
            extractor_mode=extractor_mode,
        )
    if features is None:
        return VectorizationReceipt(
            status="no_track_detected",
            features=None,
            error=None,
            candidate_count=len(candidates),
            extractor_mode=extractor_mode,
        )
    return VectorizationReceipt(
        status="ok",
        features=features,
        error=None,
        candidate_count=len(candidates),
        extractor_mode=extractor_mode,
    )
