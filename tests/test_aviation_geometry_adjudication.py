from __future__ import annotations

import pytest

from skywatcher.core.aviation_geometry_adjudication import (
    AdjudicationState,
    GeometryEvidence,
    GeometrySourceManifestation,
    IdentityAdjudication,
    IdentityEvidence,
    SourceAuthority,
    SpatialState,
    adjudicate_identity,
    adjudicate_spatial_relation,
)


@pytest.mark.parametrize(
    "evidence",
    [
        IdentityEvidence.PROXIMITY_ONLY,
        IdentityEvidence.NAME_ONLY,
        IdentityEvidence.ADDRESS_ONLY,
        IdentityEvidence.NONE,
    ],
)
def test_heuristic_only_evidence_never_certifies_identity(evidence: IdentityEvidence) -> None:
    state = adjudicate_identity(
        IdentityAdjudication(
            evidence=evidence,
            geometry_evidence=GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY,
            independent_binding_count=99,
        )
    )
    assert state == AdjudicationState.CANDIDATE_NOT_IDENTITY


def test_geometry_plus_alias_requires_certified_geometry_and_independent_binding() -> None:
    assert (
        adjudicate_identity(
            IdentityAdjudication(
                evidence=IdentityEvidence.GEOMETRY_PLUS_ALIAS_OR_ID,
                geometry_evidence=GeometryEvidence.AUTHORITATIVE_CARTOGRAPHIC,
                independent_binding_count=1,
            )
        )
        == AdjudicationState.OPEN
    )
    assert (
        adjudicate_identity(
            IdentityAdjudication(
                evidence=IdentityEvidence.GEOMETRY_PLUS_ALIAS_OR_ID,
                geometry_evidence=GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY,
                independent_binding_count=1,
            )
        )
        == AdjudicationState.CERTIFIED
    )


def test_authoritative_diagram_is_not_silently_promoted_to_machine_geometry() -> None:
    source = GeometrySourceManifestation(
        source_id="FAA_SIG_APD_2026",
        source_authority=SourceAuthority.AUTHORITATIVE,
        geometry_evidence=GeometryEvidence.AUTHORITATIVE_CARTOGRAPHIC,
        raw_name="FERNANDO LUIS RIBAS DOMINICCI (SIG) (TJIG)",
        normalized_name="Fernando Luis Ribas Dominicci (SIG) (TJIG)",
        canonical_name="Fernando Luis Ribas Dominicci Airport",
        stable_id="TJIG",
        source_url="https://aeronav.faa.gov/d-tpp/2604/01019AD.PDF",
    )
    source.validate()
    assert source.geometry_evidence != GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY


def test_certified_geometry_requires_geometry_metadata() -> None:
    source = GeometrySourceManifestation(
        source_id="bad",
        source_authority=SourceAuthority.AUTHORITATIVE,
        geometry_evidence=GeometryEvidence.CERTIFIED_MACHINE_GEOMETRY,
        raw_name="raw",
    )
    with pytest.raises(ValueError, match="requires CRS"):
        source.validate()


def test_spatial_state_is_fail_closed_without_geometry() -> None:
    assert adjudicate_spatial_relation(geometry_available=False) == SpatialState.UNRESOLVED
    assert (
        adjudicate_spatial_relation(geometry_available=True, fully_within=True)
        == SpatialState.FULLY_WITHIN
    )
    assert (
        adjudicate_spatial_relation(geometry_available=True, intersects=True)
        == SpatialState.PARTIAL
    )
    assert (
        adjudicate_spatial_relation(geometry_available=True, touches=True)
        == SpatialState.TOUCH_ONLY
    )
    assert adjudicate_spatial_relation(geometry_available=True) == SpatialState.OUTSIDE
    assert (
        adjudicate_spatial_relation(geometry_available=True, empty=True)
        == SpatialState.NULL_EMPTY
    )
