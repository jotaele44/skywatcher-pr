"""Typed records for SATIM landscape morphology, calibration and candidate assessment."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LandscapeMetrics:
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

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "LandscapeMetrics":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    status: str
    method_version: str
    thresholds: dict[str, float]
    min_evidence_families: int | None
    calibration_fixture_ids: tuple[str, ...] = ()
    calibration_sha256s: tuple[str, ...] = ()
    holdout_fixture_ids: tuple[str, ...] = ()
    holdout_sha256s: tuple[str, ...] = ()
    objective: tuple[float, ...] = ()
    candidate_count: int = 0
    tied_best_count: int = 0
    blockers: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status in {"PROVISIONAL_POSITIVE_ONLY", "CALIBRATED", "VALIDATED"} and bool(self.thresholds) and self.min_evidence_families is not None

    @property
    def production_validated(self) -> bool:
        return self.status == "VALIDATED" and not self.blockers

    def stamps(self) -> tuple[dict[str, Any], ...]:
        out = [
            {
                "threshold_id": f"CALIBRATION:{self.profile_id}:{name}",
                "value": value,
                "status": self.status,
            }
            for name, value in sorted(self.thresholds.items())
        ]
        if self.min_evidence_families is not None:
            out.append({
                "threshold_id": f"CALIBRATION:{self.profile_id}:min_evidence_families",
                "value": self.min_evidence_families,
                "status": self.status,
            })
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "satim.landscape.calibration_profile.v0.1",
            "profile_id": self.profile_id,
            "status": self.status,
            "method_version": self.method_version,
            "thresholds": dict(self.thresholds),
            "min_evidence_families": self.min_evidence_families,
            "calibration_fixture_ids": list(self.calibration_fixture_ids),
            "calibration_sha256s": list(self.calibration_sha256s),
            "holdout_fixture_ids": list(self.holdout_fixture_ids),
            "holdout_sha256s": list(self.holdout_sha256s),
            "objective": list(self.objective),
            "candidate_count": self.candidate_count,
            "tied_best_count": self.tied_best_count,
            "blockers": list(self.blockers),
        }


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
    evidence_states: dict[str, bool | None]
    independent_positive_evidence_count: int
    competing_classes: tuple[CompetingClassScore, ...]
    top_class: str | None
    terminal_state: str
    review_required: bool
    production_promotion_authorized: bool
    thresholds_applied: tuple[dict[str, Any], ...]
    calibration_profile_id: str | None
    calibration_status: str
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
            "independent_positive_evidence_count": self.independent_positive_evidence_count,
            "competing_classes": [item.to_dict() for item in self.competing_classes],
            "top_class": self.top_class,
            "terminal_state": self.terminal_state,
            "review_required": self.review_required,
            "production_promotion_authorized": self.production_promotion_authorized,
            "thresholds_applied": [dict(item) for item in self.thresholds_applied],
            "calibration_profile_id": self.calibration_profile_id,
            "calibration_status": self.calibration_status,
            "benchmark_state": self.benchmark_state,
            "benchmark_blockers": list(self.benchmark_blockers),
            "limitations": list(self.limitations),
            "temporal_recurrence_support": self.temporal_recurrence_support,
        }
