from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

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
        }
