"""Authoritative geometry adjudication contracts for aviation micro-infrastructure.

This module keeps source manifestation, geometry, names, and identity separate.
A source may be authoritative about an airport diagram without providing certified
machine geometry for a particular hangar, apron, or helipad. Proximity and names
remain discovery signals and cannot promote identity through this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceAuthority(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    AUTHORITATIVE_ENTITY_SOURCE = "AUTHORITATIVE_ENTITY_SOURCE"
    CORROBORATED = "CORROBORATED"
    THIRD_PARTY = "THIRD_PARTY"
    UNRESOLVED = "UNRESOLVED"


class GeometryEvidence(str, Enum):
    CERTIFIED_MACHINE_GEOMETRY = "CERTIFIED_MACHINE_GEOMETRY"
    AUTHORITATIVE_CARTOGRAPHIC = "AUTHORITATIVE_CARTOGRAPHIC"
    GEOREFERENCED_DERIVATION = "GEOREFERENCED_DERIVATION"
    SCREENSHOT_ONLY = "SCREENSHOT_ONLY"
    NONE = "NONE"


class IdentityEvidence(str, Enum):
    STABLE_ID = "STABLE_ID"
    AUTHORITATIVE_BINDING = "AUTHORITATIVE_BINDING"
    GEOMETRY_PLUS_ALIAS_OR_ID = "GEOMETRY_PLUS_ALIAS_OR_ID"
    AUTHORITATIVE_ALIAS_WITH_SUPPORT = "AUTHORITATIVE_ALIAS_WITH_SUPPORT"
    PROXIMITY_ONLY = "PROXIMITY_ONLY"
    NAME_ONLY = "NAME_ONLY"
    ADDRESS_ONLY = "ADDRESS_ONLY"
    NONE = "NONE"


class AdjudicationState(str, Enum):
    CERTIFIED = "CERTIFIED"
    CANDIDATE_NOT_IDENTITY = "CANDIDATE_NOT_IDENTITY"
    AUDIT_ONLY = "AUDIT_ONLY"
    OPEN = "OPEN"
    UNRESOLVED = "UNRESOLVED"


class SpatialState(str, Enum):
    FULLY_WITHIN = "FULLY_WITHIN"
    PARTIAL = "PARTIAL"
    TOUCH_ONLY = "TOUCH_ONLY"
    OUTSIDE = "OUTSIDE"
    NULL_EMPTY = "NULL_EMPTY"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class GeometrySourceManifestation:
    source_id: str
    source_authority: SourceAuthority
    geometry_evidence: GeometryEvidence
    raw_name: str
    normalized_name: str | None = None
    canonical_name: str | None = None
    stable_id: str | None = None
    source_url: str | None = None
    crs: str | None = None
    geometry_type: str | None = None
    retrieved_utc: str | None = None
    sha256: str | None = None

    def validate(self) -> None:
        if self.geometry_evidence == GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY:
            required = (self.crs, self.geometry_type, self.source_url)
            if any(value is None or value == "" for value in required):
                raise ValueError("certified machine geometry requires CRS, geometry type, and source URL")
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        if self.canonical_name and not self.normalized_name:
            raise ValueError("canonical_name requires a separately preserved normalized_name")


@dataclass(frozen=True)
class IdentityAdjudication:
    evidence: IdentityEvidence
    geometry_evidence: GeometryEvidence
    independent_binding_count: int = 0


def adjudicate_identity(candidate: IdentityAdjudication) -> AdjudicationState:
    """Return the strongest identity state supported by bounded evidence.

    NAME_ONLY, ADDRESS_ONLY, and PROXIMITY_ONLY can never certify identity.
    A cartographic airport diagram can authoritatively establish feature classes
    and approximate topology while still leaving individual feature identity open.
    """
    if candidate.independent_binding_count < 0:
        raise ValueError("independent_binding_count cannot be negative")

    if candidate.evidence in {
        IdentityEvidence.PROXIMITY_ONLY,
        IdentityEvidence.NAME_ONLY,
        IdentityEvidence.ADDRESS_ONLY,
        IdentityEvidence.NONE,
    }:
        return AdjudicationState.CANDIDATE_NOT_IDENTITY

    if candidate.evidence == IdentityEvidence.STABLE_ID:
        return AdjudicationState.CERTIFIED

    if candidate.evidence == IdentityEvidence.AUTHORITATIVE_BINDING:
        return (
            AdjudicationState.CERTIFIED
            if candidate.independent_binding_count >= 1
            else AdjudicationState.OPEN
        )

    if candidate.evidence == IdentityEvidence.GEOMETRY_PLUS_ALIAS_OR_ID:
        return (
            AdjudicationState.CERTIFIED
            if candidate.geometry_evidence == GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY
            and candidate.independent_binding_count >= 1
            else AdjudicationState.OPEN
        )

    if candidate.evidence == IdentityEvidence.AUTHORITATIVE_ALIAS_WITH_SUPPORT:
        return (
            AdjudicationState.CERTIFIED
            if candidate.independent_binding_count >= 2
            else AdjudicationState.OPEN
        )

    return AdjudicationState.UNRESOLVED


def adjudicate_spatial_relation(
    *,
    geometry_available: bool,
    fully_within: bool = False,
    intersects: bool = False,
    touches: bool = False,
    empty: bool = False,
) -> SpatialState:
    """Collapse exact-topology outputs to the canonical six-state vocabulary."""
    if empty:
        return SpatialState.NULL_EMPTY
    if not geometry_available:
        return SpatialState.UNRESOLVED
    if fully_within:
        return SpatialState.FULLY_WITHIN
    if touches and not intersects:
        return SpatialState.TOUCH_ONLY
    if intersects:
        return SpatialState.PARTIAL
    return SpatialState.OUTSIDE
