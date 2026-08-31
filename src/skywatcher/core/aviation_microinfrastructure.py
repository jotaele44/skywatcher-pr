"""Aviation micro-infrastructure and landing-zone truth contracts.

This module deliberately separates physical geometry, observed aircraft activity,
operator identity, and terminal-event association.  It prevents proximity or a
single parked aircraft from silently promoting an apron/hangar into a helipad.

The contract is dependency-free: spatial engines may compute exact relations
elsewhere and pass the resulting :class:`SpatialRelation` here.  That keeps the
truth policy deterministic and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PhysicalClass(str, Enum):
    HANGAR = "HANGAR"
    HELIPAD = "HELIPAD"
    APRON = "APRON"
    FBO = "FBO"
    ATC = "ATC"
    TERMINAL = "TERMINAL"
    GOVERNMENT_COMPOUND = "GOVERNMENT_COMPOUND"
    NON_AVIATION_ADJACENCY = "NON_AVIATION_ADJACENCY"


class LandingSurfaceType(str, Enum):
    RUNWAY = "RUNWAY"
    HELIPAD = "HELIPAD"
    WATER = "WATER"
    NONE = "NONE"
    UNRESOLVED = "UNRESOLVED"


class HelipadEvidence(str, Enum):
    MARKED_H = "MARKED_H"
    PUBLISHED = "PUBLISHED"
    AIRPORT_RECORD = "AIRPORT_RECORD"
    REPEATED_OPERATION = "REPEATED_OPERATION"
    NONE = "NONE"


class BindingState(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    CORROBORATED = "CORROBORATED"
    CANDIDATE = "CANDIDATE"
    UNRESOLVED = "UNRESOLVED"


class GeometryState(str, Enum):
    CERTIFIED = "CERTIFIED"
    OBSERVED_UNGEOREFERENCED = "OBSERVED_UNGEOREFERENCED"
    CANDIDATE = "CANDIDATE"
    UNRESOLVED = "UNRESOLVED"


class SpatialRelation(str, Enum):
    LANDING_SURFACE_EXACT = "LANDING_SURFACE_EXACT"
    LANDING_SURFACE_UNCERTAINTY = "LANDING_SURFACE_UNCERTAINTY"
    APRON = "APRON"
    FACILITY_COMPOUND = "FACILITY_COMPOUND"
    NEAREST_ONLY = "NEAREST_ONLY"
    OUTSIDE = "OUTSIDE"
    UNRESOLVED = "UNRESOLVED"


class TerminalAssociation(str, Enum):
    LANDING_SURFACE_ASSOCIATED = "LANDING_SURFACE_ASSOCIATED"
    LANDING_SURFACE_CANDIDATE = "LANDING_SURFACE_CANDIDATE"
    APRON_ARRIVAL = "APRON_ARRIVAL"
    FACILITY_ASSOCIATED_CANDIDATE = "FACILITY_ASSOCIATED_CANDIDATE"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    OUTSIDE = "OUTSIDE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class AviationMicrofacility:
    facility_id: str
    airfield_id: str
    physical_class: PhysicalClass
    facility_name_raw: str
    facility_name_normalized: str | None = None
    canonical_name: str | None = None
    operator_raw: str | None = None
    operator_id: str | None = None
    operator_binding_state: BindingState = BindingState.UNRESOLVED
    footprint_geometry_state: GeometryState = GeometryState.UNRESOLVED
    apron_geometry_state: GeometryState = GeometryState.UNRESOLVED
    landing_surface_geometry_state: GeometryState = GeometryState.UNRESOLVED
    landing_surface_type: LandingSurfaceType = LandingSurfaceType.NONE
    helipad_evidence: HelipadEvidence = HelipadEvidence.NONE
    rotor_activity_observed: bool = False
    fixed_wing_activity_observed: bool = False
    source_manifestation: str | None = None
    source_observation_id: str | None = None

    def validate(self) -> None:
        """Fail closed on internally contradictory physical claims."""
        if self.physical_class == PhysicalClass.NON_AVIATION_ADJACENCY:
            if self.landing_surface_type != LandingSurfaceType.NONE:
                raise ValueError("non-aviation adjacency cannot be a landing surface")
            if self.helipad_evidence != HelipadEvidence.NONE:
                raise ValueError("non-aviation adjacency cannot carry helipad evidence")

        if (
            self.landing_surface_type == LandingSurfaceType.HELIPAD
            and self.helipad_evidence == HelipadEvidence.NONE
        ):
            raise ValueError("helipad landing surface requires positive helipad evidence")

        if self.operator_id is not None and self.operator_binding_state == BindingState.UNRESOLVED:
            raise ValueError("operator_id requires a resolved binding state")


def classify_terminal_event(relation: SpatialRelation) -> TerminalAssociation:
    """Map an independently computed spatial relation to a bounded truth state.

    Nearest-neighbour proximity is intentionally discovery-only.  It can never
    become facility identity or a landing claim through this function.
    """
    mapping = {
        SpatialRelation.LANDING_SURFACE_EXACT: TerminalAssociation.LANDING_SURFACE_ASSOCIATED,
        SpatialRelation.LANDING_SURFACE_UNCERTAINTY: TerminalAssociation.LANDING_SURFACE_CANDIDATE,
        SpatialRelation.APRON: TerminalAssociation.APRON_ARRIVAL,
        SpatialRelation.FACILITY_COMPOUND: TerminalAssociation.FACILITY_ASSOCIATED_CANDIDATE,
        SpatialRelation.NEAREST_ONLY: TerminalAssociation.DISCOVERY_ONLY,
        SpatialRelation.OUTSIDE: TerminalAssociation.OUTSIDE,
        SpatialRelation.UNRESOLVED: TerminalAssociation.UNRESOLVED,
    }
    return mapping[relation]


def can_promote_to_physical_helipad(facility: AviationMicrofacility) -> bool:
    """Return whether evidence supports existence of a physical helipad.

    Rotorcraft presence by itself is deliberately insufficient.  At least one
    explicit helipad evidence channel must exist, and the landing-surface type
    must already be HELIPAD.
    """
    facility.validate()
    return (
        facility.landing_surface_type == LandingSurfaceType.HELIPAD
        and facility.helipad_evidence != HelipadEvidence.NONE
    )
