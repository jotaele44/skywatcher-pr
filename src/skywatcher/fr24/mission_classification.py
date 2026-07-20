"""GATED MISSION CLASSIFICATION (revised no-intent policy)

Policy change (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md, revised): mission /
intent inference is no longer *forbidden*; it is permitted but treated as
**highly speculative** until the supporting evidence score surpasses a high
threshold gate. Only above the gate may a classification be labeled
``evidence_gated`` (a firmer, but still non-"confirmed", status).

This module implements the gate. It is deliberately:

* code-only — it never opens an operational database or reads screenshots;
* scorer-agnostic — callers pass an evidence score (0..1) and a candidate
  label; the gate decides the *status*, never fabricating a "confirmed" verdict;
* fail-safe — anything at or below the gate is ``highly_speculative``.

The legacy heuristic deducer (``skywatcher.legacy.quarantined_mission_inference``)
remains available for callers that already hold in-memory flight characteristics,
but its output MUST be passed through :func:`classify` so the speculative gate is
always applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "HIGH_THRESHOLD",
    "MissionClassificationStatus",
    "MissionClassification",
    "classify",
]

# High-confidence gate. Evidence at or below this remains speculative.
HIGH_THRESHOLD = 0.85

# Terminal-accept tokens are never emitted by this gate (contradiction C2):
# gated classification tops out at "evidence_gated", not "confirmed".
_HIGHLY_SPECULATIVE = "highly_speculative"
_EVIDENCE_GATED = "evidence_gated"


class MissionClassificationStatus:
    HIGHLY_SPECULATIVE = _HIGHLY_SPECULATIVE
    EVIDENCE_GATED = _EVIDENCE_GATED


@dataclass(frozen=True)
class MissionClassification:
    """A gated mission classification result.

    ``status`` is ``highly_speculative`` unless ``evidence_score`` strictly
    exceeds :data:`HIGH_THRESHOLD`, in which case it is ``evidence_gated``.
    """

    value: Optional[str]
    evidence_score: float
    status: str
    threshold: float = HIGH_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "evidence_score": self.evidence_score,
            "status": self.status,
            "threshold": self.threshold,
        }


def classify(
    value: Optional[str],
    evidence_score: float,
    *,
    threshold: float = HIGH_THRESHOLD,
) -> MissionClassification:
    """Apply the speculative gate to a candidate mission ``value``.

    Args:
        value: candidate mission label (may be None / "Unknown").
        evidence_score: supporting-evidence strength in [0, 1].
        threshold: gate; scores strictly above it are promoted.

    Returns a :class:`MissionClassification` whose status reflects the gate.
    """
    try:
        score = float(evidence_score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    status = _EVIDENCE_GATED if score > threshold else _HIGHLY_SPECULATIVE
    # Below the gate we keep the candidate label but flag it speculative; we do
    # not blank it (the label is a hypothesis, the status conveys the caveat).
    return MissionClassification(
        value=value,
        evidence_score=score,
        status=status,
        threshold=threshold,
    )
