"""Typed records for SATIM landscape morphology and land-use candidate assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LandscapeMetrics:
    """Continuous, scene-level measurements extracted from one image.

    These are observations/derived features, not land-use identities. All fractions
    and scores are bounded to [0, 1].
    """

    width_px: int
    height_px: int
    analysis_width_px: int
    analysis_height_px: int
    vegetation_fraction: float
    forest_matrix_fraction: float
    open_surface_fraction: float
    exposed_soil_fraction: float
    bright_cover_fraction: float
    directional_texture_score: float
    patch_mosaic_score: float
    extraction_method: str
    extraction_constants: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompetingClassScore:
    class_name: str
    score: float | None
    evaluated: bool
    supporting_evidence: tuple[str, ...] = ()
    contradicting_evidence: tuple[str, ...] = ()
    unevaluated_requirements: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "score": self.score,
            "evaluated": self.evaluated,
            "supporting_evidence": list(self.supporting_evidence),
            "contradicting_evidence": list(self.contradicting_evidence),
            "unevaluated_requirements": list(self.unevaluated_requirements),
        }


@dataclass(frozen=True)
class LandscapeAssessment:
    schema_version: str
    method_version: str
    source_sha256: str
    source_path: str
    metrics: LandscapeMetrics
    evidence_states: dict[str, bool]
    competing_classes: tuple[CompetingClassScore, ...]
    top_class: str | None
    terminal_state: str
    review_required: bool
    production_promotion_authorized: bool
    thresholds_applied: tuple[dict[str, Any], ...]
    benchmark_state: str
    benchmark_blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    temporal_recurrence_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "method_version": self.method_version,
            "source": {"sha256": self.source_sha256, "path": self.source_path},
            "metrics": self.metrics.to_dict(),
            "evidence_states": dict(self.evidence_states),
            "competing_classes": [item.to_dict() for item in self.competing_classes],
            "top_class": self.top_class,
            "terminal_state": self.terminal_state,
            "review_required": self.review_required,
            "production_promotion_authorized": self.production_promotion_authorized,
            "thresholds_applied": [dict(item) for item in self.thresholds_applied],
            "benchmark_state": self.benchmark_state,
            "benchmark_blockers": list(self.benchmark_blockers),
            "limitations": list(self.limitations),
            "temporal_recurrence_support": self.temporal_recurrence_support,
        }
