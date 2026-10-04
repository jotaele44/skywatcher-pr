"""Legacy mission-classification compatibility gate.

Active PITIRRE/Skywatcher ontology v2.1 prohibits mission or intent inference.
This module remains importable only so historical callers can read/replay the
former speculative gate. Canonical code must not call it.

Calling classify() without an explicit legacy_compat=True opt-in fails closed.
Even with the opt-in, the returned object is marked active_use_allowed=False
and may not be exported as a canonical finding.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "HIGH_THRESHOLD",
    "MissionInferenceProhibitedError",
    "MissionClassificationStatus",
    "MissionClassification",
    "classify",
]

HIGH_THRESHOLD = 0.85
_HIGHLY_SPECULATIVE = "highly_speculative"
_EVIDENCE_GATED = "evidence_gated"


class MissionInferenceProhibitedError(RuntimeError):
    """Raised when active code attempts mission/intent inference."""


class MissionClassificationStatus:
    HIGHLY_SPECULATIVE = _HIGHLY_SPECULATIVE
    EVIDENCE_GATED = _EVIDENCE_GATED


@dataclass(frozen=True)
class MissionClassification:
    """Historical gated result retained for replay/compatibility only."""

    value: str | None
    evidence_score: float
    status: str
    threshold: float = HIGH_THRESHOLD
    active_use_allowed: bool = False
    canonical_state: str = "LEGACY_QUARANTINED"

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "evidence_score": self.evidence_score,
            "status": self.status,
            "threshold": self.threshold,
            "active_use_allowed": self.active_use_allowed,
            "canonical_state": self.canonical_state,
        }


def classify(
    value: str | None,
    evidence_score: float,
    *,
    threshold: float = HIGH_THRESHOLD,
    legacy_compat: bool = False,
) -> MissionClassification:
    """Replay the historical speculative gate only with explicit legacy opt-in."""
    if not legacy_compat:
        raise MissionInferenceProhibitedError(
            "mission/intent inference is prohibited by active ontology v2.1; "
            "use source-declared labels or explicit Legacy replay"
        )
    try:
        score = float(evidence_score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    status = _EVIDENCE_GATED if score > threshold else _HIGHLY_SPECULATIVE
    return MissionClassification(
        value=value,
        evidence_score=score,
        status=status,
        threshold=threshold,
    )
