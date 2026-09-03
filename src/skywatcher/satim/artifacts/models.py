from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

CONFIDENCE_LEVELS = (
    (0.90, "CONFIRMED"),
    (0.75, "HIGH"),
    (0.50, "MODERATE"),
    (0.25, "LOW"),
    (0.0, "UNRESOLVED"),
)


def confidence_level(score: float) -> str:
    score = max(0.0, min(1.0, float(score)))
    for threshold, level in CONFIDENCE_LEVELS:
        if score >= threshold:
            return level
    return "UNRESOLVED"


@dataclass(frozen=True)
class AssessmentResult:
    """Outcome of one artifact assessment.

    The trailing fields are additive (ADR v2.0 section 13.2) and all default to empty,
    so a caller that supplies no lens registry gets byte-identical v1 behavior. They
    exist to answer questions the v1 result could not:

      * which lenses ran, and what each one's coverage state was;
      * which requirements went unmet, so a skipped check is distinguishable from a
        check that ran and found nothing;
      * which thresholds were executed and at what governance status, per ADR v2.1 A2;
      * whether the requested interpretation restriction was actually honored -
        previously the gate's ``allowed``/``reason`` were computed and discarded, so a
        rejected request silently degraded to the minimum.
    """

    primary_class: str
    contributing_classes: tuple[str, ...]
    origin_layer: str
    classification_confidence: float
    origin_confidence: float
    confidence_level: str
    interpretation_restriction: str
    contradictions: tuple[str, ...] = ()
    rules_triggered: tuple[str, ...] = ()
    measurements: Mapping[str, Any] = field(default_factory=dict)
    lenses_applied: tuple[str, ...] = ()
    lens_coverage: tuple[Mapping[str, Any], ...] = ()
    unsatisfied_requirements: tuple[str, ...] = ()
    thresholds_applied: tuple[Mapping[str, Any], ...] = ()
    restriction_allowed: bool = True
    restriction_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_class": self.primary_class,
            "contributing_classes": list(self.contributing_classes),
            "origin_layer": self.origin_layer,
            "classification_confidence": self.classification_confidence,
            "origin_confidence": self.origin_confidence,
            "confidence_level": self.confidence_level,
            "interpretation_restriction": self.interpretation_restriction,
            "contradictions": list(self.contradictions),
            "rules_triggered": list(self.rules_triggered),
            "measurements": dict(self.measurements),
            "lenses_applied": list(self.lenses_applied),
            "lens_coverage": [dict(entry) for entry in self.lens_coverage],
            "unsatisfied_requirements": list(self.unsatisfied_requirements),
            "thresholds_applied": [dict(t) for t in self.thresholds_applied],
            "restriction_allowed": self.restriction_allowed,
            "restriction_reason": self.restriction_reason,
        }
