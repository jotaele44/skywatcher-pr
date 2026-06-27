"""SATIM Phase 1 candidate extraction stub.

This module defines the contract between raw imagery/screenshot inputs and the
existing SATIM L5 classifiers. It intentionally performs conservative metadata
normalization only; raster edge extraction, GIS joins, and multi-date imagery
comparison are follow-on implementation layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "satim.visual_ledger.v1"

CANDIDATE_KINDS = {
    "linear_boundary",
    "rectilinear_boundary",
    "tonal_boundary",
    "ui_overlay_candidate",
    "track_line_candidate",
    "mixed_epoch_candidate",
    "other",
}

DEFAULT_FEATURE_SCORES = {
    "straightness": 0.0,
    "radiometric_delta": 0.0,
    "terrain_crossing": 0.0,
    "landcover_persistence": 0.0,
    "coastal_crossing_score": 0.0,
    "road_alignment": 0.0,
    "building_alignment": 0.0,
    "airport_alignment": 0.0,
    "parcel_alignment": 0.0,
    "screen_locked_score": 0.0,
    "track_line_overlap": 0.0,
    "ui_overlay_overlap": 0.0,
    "multi_date_persistence": 0.0,
}


def clamp01(value: Any) -> float:
    """Return a numeric score bounded to [0, 1]."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SatimVisualCandidate:
    """Normalized SATIM visual-ledger candidate row."""

    visual_id: str
    source_image_id: str
    source_uri: str
    capture_datetime_utc: str
    aoi_id: str
    candidate_kind: str
    geometry: Mapping[str, Any]
    feature_scores: Mapping[str, float] = field(default_factory=dict)
    classification: str = "indeterminate"
    confidence: float = 0.0
    review_state: str = "unreviewed"
    imagery_provider: str | None = None
    imagery_epoch: str | None = None
    municipality: str | None = None
    contradiction_flags: tuple[str, ...] = ()
    cross_source_refs: tuple[str, ...] = ()
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str | None = None

    def to_ledger_row(self) -> dict[str, Any]:
        if self.candidate_kind not in CANDIDATE_KINDS:
            raise ValueError(f"unsupported SATIM candidate_kind: {self.candidate_kind}")
        scores = dict(DEFAULT_FEATURE_SCORES)
        scores.update({key: clamp01(value) for key, value in self.feature_scores.items()})
        return {
            "schema_version": SCHEMA_VERSION,
            "visual_id": self.visual_id,
            "source_image_id": self.source_image_id,
            "source_uri": self.source_uri,
            "capture_datetime_utc": self.capture_datetime_utc,
            "imagery_provider": self.imagery_provider,
            "imagery_epoch": self.imagery_epoch,
            "aoi_id": self.aoi_id,
            "municipality": self.municipality,
            "geometry": dict(self.geometry),
            "candidate_kind": self.candidate_kind,
            "feature_scores": scores,
            "classification": self.classification,
            "confidence": clamp01(self.confidence),
            "review_state": self.review_state,
            "reviewer": None,
            "review_note": None,
            "contradiction_flags": list(self.contradiction_flags),
            "cross_source_refs": list(self.cross_source_refs),
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }


def normalize_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a raw candidate mapping into the SATIM visual ledger contract.

    Required raw keys mirror the ledger schema. Feature scores are accepted either
    under ``feature_scores`` or as top-level known feature columns.
    """
    feature_scores = dict(row.get("feature_scores") or {})
    for key in DEFAULT_FEATURE_SCORES:
        if key in row:
            feature_scores[key] = row[key]

    candidate = SatimVisualCandidate(
        visual_id=str(row["visual_id"]),
        source_image_id=str(row["source_image_id"]),
        source_uri=str(row["source_uri"]),
        capture_datetime_utc=str(row["capture_datetime_utc"]),
        imagery_provider=row.get("imagery_provider"),
        imagery_epoch=row.get("imagery_epoch"),
        aoi_id=str(row["aoi_id"]),
        municipality=row.get("municipality"),
        geometry=row["geometry"],
        candidate_kind=str(row.get("candidate_kind", "other")),
        feature_scores=feature_scores,
        classification=str(row.get("classification", "indeterminate")),
        confidence=clamp01(row.get("confidence", 0.0)),
        review_state=str(row.get("review_state", "unreviewed")),
        contradiction_flags=tuple(row.get("contradiction_flags") or ()),
        cross_source_refs=tuple(row.get("cross_source_refs") or ()),
        created_at_utc=str(row.get("created_at_utc") or utc_now_iso()),
        updated_at_utc=row.get("updated_at_utc"),
    )
    return candidate.to_ledger_row()
