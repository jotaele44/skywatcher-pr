"""Shared confidence-grading utility (Core; importable by any domain).

Reconciles the two confidence scales used across Skywatcher:

* the legacy 0..1 float on ``AircraftProfile.confidence_level`` and the
  ``aircraft_intelligence_report`` schema, and
* the 5-grade evidence scale the ``skywatcher-airspace-evidence`` skill uses in
  its finding envelope: VERIFIED / HIGH / MODERATE / LOW / INSUFFICIENT.

``grade()`` implements the skill's coverage-gate caps
(references/coverage-gates.md) so no aggregate is graded above what its evidence
supports:

* recurrence / cadence claims with **no eligible-period denominator** are
  capped below HIGH (i.e. at most MODERATE);
* **spatial** claims without georeferencing are capped at most MODERATE;
* claims with **no source/receiver context** are capped at most LOW.

This lives in Core (like ``geo_utils``) because both the FPIM profile builder
and the query layer need it, and Core is the only bucket importable by all
(see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ordered weakest -> strongest. Index is the ordinal used for min-capping.
GRADES: list[str] = ["INSUFFICIENT", "LOW", "MODERATE", "HIGH", "VERIFIED"]

# Evidence tiers, aligned with the repo schemas (flight_event.schema.json etc.).
TIER_TECHNICAL = "T1"
TIER_OPERATIONAL = "T2"
TIER_EYEWITNESS = "T3"
TIER_SECONDARY = "T4"

_GRADE_TO_FLOAT = {
    "VERIFIED": 0.95,
    "HIGH": 0.85,
    "MODERATE": 0.60,
    "LOW": 0.35,
    "INSUFFICIENT": 0.10,
}


@dataclass
class Grade:
    """Result of grading one aggregate/finding."""

    confidence_grade: str
    evidence_tier: str
    confidence_level: float
    caps_applied: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "confidence_grade": self.confidence_grade,
            "evidence_tier": self.evidence_tier,
            "confidence_level": self.confidence_level,
            "caps_applied": list(self.caps_applied),
        }


def _ordinal(grade: str) -> int:
    return GRADES.index(grade)


def _cap(current: str, ceiling: str, caps: list[str], reason: str) -> str:
    """Lower ``current`` to ``ceiling`` when it exceeds it, recording ``reason``."""
    if _ordinal(current) > _ordinal(ceiling):
        caps.append(reason)
        return ceiling
    return current


def grade_to_float(grade: str) -> float:
    """Representative 0..1 value for a grade (for the legacy float scale)."""
    return _GRADE_TO_FLOAT.get(grade, 0.10)


def float_to_grade(value: float | None) -> str:
    """Map a 0..1 confidence float onto the 5-grade scale."""
    if value is None:
        return "INSUFFICIENT"
    if value >= 0.90:
        return "VERIFIED"
    if value >= 0.75:
        return "HIGH"
    if value >= 0.50:
        return "MODERATE"
    if value >= 0.25:
        return "LOW"
    return "INSUFFICIENT"


def grade(
    *,
    observation_count: int,
    denominator: int | None = None,
    is_ground_truth: bool = False,
    is_spatial: bool = False,
    has_georef: bool = True,
    has_source_context: bool = True,
) -> Grade:
    """Grade one aggregate from its evidence, applying coverage-gate caps.

    Parameters
    ----------
    observation_count:
        How many times the thing was observed (route sightings, endpoint hits…).
    denominator:
        Eligible periods (e.g. distinct flight-days). ``None`` / 0 means the
        recurrence denominator is unknown → capped below HIGH.
    is_ground_truth:
        Operator-declared reference data (``KNOWN_OPERATORS``); can reach VERIFIED.
    is_spatial:
        Whether this is a spatial claim (home base / LZ) subject to the georef cap.
    has_georef:
        Whether georeferenced positions back a spatial claim.
    has_source_context:
        Whether source/receiver context is available (termination-style claims).
    """
    caps: list[str] = []

    if is_ground_truth:
        base = "VERIFIED"
    elif denominator and denominator > 0:
        ratio = observation_count / denominator
        if observation_count >= 5 and ratio >= 0.5:
            base = "HIGH"
        elif observation_count >= 3 and ratio >= 0.25:
            base = "MODERATE"
        elif observation_count >= 1:
            base = "LOW"
        else:
            base = "INSUFFICIENT"
    else:
        # No denominator: strength from raw count only, and capped below HIGH.
        if observation_count >= 3:
            base = "MODERATE"
        elif observation_count >= 1:
            base = "LOW"
        else:
            base = "INSUFFICIENT"

    if not is_ground_truth:
        if not denominator or denominator <= 0:
            base = _cap(base, "MODERATE", caps, "no_denominator_recurrence_capped_below_high")
        if is_spatial and not has_georef:
            base = _cap(base, "MODERATE", caps, "no_georef_spatial_capped")
        if not has_source_context:
            base = _cap(base, "LOW", caps, "no_source_context_capped")

    if is_ground_truth:
        tier = TIER_TECHNICAL
    elif observation_count > 0 and denominator and denominator > 0:
        tier = TIER_OPERATIONAL
    elif observation_count > 0:
        tier = TIER_EYEWITNESS
    else:
        tier = TIER_SECONDARY

    return Grade(
        confidence_grade=base,
        evidence_tier=tier,
        confidence_level=grade_to_float(base),
        caps_applied=caps,
    )
