"""Conservative behavior-truth gates for aircraft screenshot analysis.

This module deliberately separates observation from inference.  It is pure and
side-effect free so the same rules can be reused by RLSM, FPIM/CORRIM/SATIM,
timeline, and pattern layers without allowing a downstream classifier to turn
proximity, a tracker field, or a single zero-speed sample into an event fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class Certification(str, Enum):
    PASS = "PASS"
    PROVISIONAL = "PROVISIONAL"
    CANDIDATE_NOT_IDENTITY = "CANDIDATE_NOT_IDENTITY"
    UNRESOLVED = "UNRESOLVED"


class AltitudeState(str, Enum):
    INFORMATIVE = "INFORMATIVE"
    NONINFORMATIVE = "NONINFORMATIVE"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


class MotionState(str, Enum):
    MOVING = "MOVING"
    STATIONARY_POSITION = "STATIONARY_POSITION"
    HOVER_OR_GROUND_UNRESOLVED = "HOVER_OR_GROUND_UNRESOLVED"


class LandingState(str, Enum):
    NOT_INDICATED = "NOT_INDICATED"
    CANDIDATE = "LANDING_CANDIDATE"
    CERTIFIED = "LANDING_CERTIFIED"
    UNRESOLVED = "UNRESOLVED"


class AssociationState(str, Enum):
    LINEAR_INFRASTRUCTURE_ALIGNED = "LINEAR_INFRASTRUCTURE_ALIGNED"
    SITE_ASSOCIATION_SUPPORTED = "SITE_ASSOCIATION_SUPPORTED"
    NO_SITE_ASSOCIATION_PROVEN = "NO_SITE_ASSOCIATION_PROVEN"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class AltitudeAssessment:
    state: AltitudeState
    certification: Certification
    reason: str


@dataclass(frozen=True)
class LandingAssessment:
    motion_state: MotionState
    landing_state: LandingState
    certification: Certification
    reason: str


@dataclass(frozen=True)
class AssociationAssessment:
    state: AssociationState
    certification: Certification
    reason: str


def assess_baro_altitude(
    barometric_alt_ft: float | None,
    *,
    ground_speed_mph: float | None,
    rendered_track_crosses_non_ground_surface: bool = False,
) -> AltitudeAssessment:
    """Reject the FR24-style ``0 ft == on ground`` shortcut.

    A zero/near-zero barometric field is non-informative when independent
    movement evidence shows that treating it literally would contradict the
    observed route.  This function does not estimate true altitude.
    """
    if barometric_alt_ft is None:
        return AltitudeAssessment(
            AltitudeState.UNKNOWN,
            Certification.UNRESOLVED,
            "barometric altitude is absent",
        )
    moving = ground_speed_mph is not None and ground_speed_mph > 3.0
    if abs(barometric_alt_ft) <= 1.0 and (
        moving or rendered_track_crosses_non_ground_surface
    ):
        return AltitudeAssessment(
            AltitudeState.CONTRADICTED,
            Certification.PASS,
            "zero barometric altitude conflicts with independent movement/route evidence",
        )
    if abs(barometric_alt_ft) <= 1.0:
        return AltitudeAssessment(
            AltitudeState.NONINFORMATIVE,
            Certification.PROVISIONAL,
            "zero barometric altitude alone cannot establish ground contact",
        )
    return AltitudeAssessment(
        AltitudeState.INFORMATIVE,
        Certification.PROVISIONAL,
        "non-zero tracker altitude retained as an observation, not an AGL truth claim",
    )


def assess_landing(
    speeds_mph: Iterable[float | None],
    *,
    stationary_samples: int,
    independent_ground_contact: bool = False,
    later_departure_same_position: bool = False,
) -> LandingAssessment:
    """Keep a stop distinct from a landing.

    A landing is certified only by independent ground-contact evidence or a
    stop/departure sequence that independently binds the same position.  A
    tracker zero-speed endpoint by itself remains a candidate.
    """
    values = [v for v in speeds_mph if v is not None]
    has_motion = any(v > 3.0 for v in values)
    has_stop = any(v <= 1.0 for v in values) or stationary_samples > 0

    if independent_ground_contact or (stationary_samples >= 2 and later_departure_same_position):
        return LandingAssessment(
            MotionState.STATIONARY_POSITION,
            LandingState.CERTIFIED,
            Certification.PASS,
            "ground contact independently supported",
        )
    if has_motion and has_stop:
        return LandingAssessment(
            MotionState.HOVER_OR_GROUND_UNRESOLVED,
            LandingState.CANDIDATE,
            Certification.PROVISIONAL,
            "moving-to-stationary sequence observed without independent ground contact",
        )
    if has_stop:
        return LandingAssessment(
            MotionState.STATIONARY_POSITION,
            LandingState.UNRESOLVED,
            Certification.UNRESOLVED,
            "stationary observation is insufficient to distinguish hover from ground contact",
        )
    return LandingAssessment(
        MotionState.MOVING,
        LandingState.NOT_INDICATED,
        Certification.PASS,
        "no stationary endpoint is present",
    )


def assess_site_association(
    *,
    proximity_only: bool,
    independent_site_binding: bool,
    corridor_alignment_supported: bool,
) -> AssociationAssessment:
    """Prevent map-label/nearest-POI target hallucination.

    Proximity, labels, category agreement, or deterministic nearest-neighbour
    selection are discovery signals only.  Corridor alignment can be reported
    as an association class, but it does not identify a mission target.
    """
    if independent_site_binding:
        return AssociationAssessment(
            AssociationState.SITE_ASSOCIATION_SUPPORTED,
            Certification.PASS,
            "site relationship has independent evidence beyond proximity",
        )
    if corridor_alignment_supported:
        return AssociationAssessment(
            AssociationState.LINEAR_INFRASTRUCTURE_ALIGNED,
            Certification.PROVISIONAL,
            "trajectory aligns with linear infrastructure; target identity remains unproven",
        )
    if proximity_only:
        return AssociationAssessment(
            AssociationState.NO_SITE_ASSOCIATION_PROVEN,
            Certification.CANDIDATE_NOT_IDENTITY,
            "proximity/map label alone cannot establish a target relationship",
        )
    return AssociationAssessment(
        AssociationState.UNRESOLVED,
        Certification.UNRESOLVED,
        "insufficient evidence for site or corridor association",
    )


def mission_family_from_context(
    *,
    owner_or_operator_utility_context: bool,
    corridor_alignment_supported: bool,
    independent_mission_record: bool,
) -> tuple[str, Certification]:
    """Return a bounded mission family without promoting context to fact."""
    if independent_mission_record:
        return "UTILITY_MISSION_SUPPORTED", Certification.PASS
    if owner_or_operator_utility_context and corridor_alignment_supported:
        return "UTILITY_INSPECTION_OR_MAINTENANCE_FAMILY", Certification.PROVISIONAL
    return "MISSION_UNKNOWN", Certification.UNRESOLVED
