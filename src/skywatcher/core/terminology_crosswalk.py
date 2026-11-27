"""Non-destructive vocabulary compatibility helpers for Skywatcher v0.4.

This is an internal-only adapter. It does not modify the governing ingestion
contract, classify sites, or certify claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EVIDENCE_STATES = frozenset({
    "FACT", "COMPUTED", "BINDING", "INFERENCE", "ASSUMPTION", "HYPOTHESIS", "UNKNOWN"
})
CERTIFICATION_STATES = frozenset({
    "PASS", "FAIL", "OPEN", "BLOCKED", "PROVISIONAL", "AUDIT_ONLY",
    "NONCANONICAL", "CANDIDATE_NOT_IDENTITY", "UNRESOLVED", "SUPERSEDED"
})
# Display terms are not governing stored enums. Each mapping is contextual,
# never a proof of a certification outcome.
DISPLAY_EVIDENCE_HINTS = {
    "OBSERVED": "FACT",
    "DERIVED": "COMPUTED",
    "INFERRED": "INFERENCE",
    "HYPOTHESIZED": "HYPOTHESIS",
}
AMBIGUOUS_CERTIFICATION_TERMS = frozenset({"VERIFIED", "REJECTED"})


@dataclass(frozen=True)
class TerminologyResolution:
    original: str
    normalized: str | None
    vocabulary: Literal["evidence", "certification"]
    status: Literal["CANONICAL", "ALIAS_REQUIRES_REVIEW", "UNRESOLVED"]
    explanation: str


def resolve_term(term: str, vocabulary: Literal["evidence", "certification"]) -> TerminologyResolution:
    """Resolve vocabulary conservatively; never silently certify or overwrite raw values."""
    raw = term
    token = term.strip().upper()
    canonical = EVIDENCE_STATES if vocabulary == "evidence" else CERTIFICATION_STATES
    if token in canonical:
        return TerminologyResolution(raw, token, vocabulary, "CANONICAL", "Governing enum")
    if vocabulary == "evidence" and token in DISPLAY_EVIDENCE_HINTS:
        return TerminologyResolution(
            raw, DISPLAY_EVIDENCE_HINTS[token], vocabulary,
            "ALIAS_REQUIRES_REVIEW",
            "Proposed display alias; source and method must be checked before persistence",
        )
    return TerminologyResolution(
        raw, None, vocabulary, "UNRESOLVED",
        "No safe automatic conversion; preserve original and require review",
    )
