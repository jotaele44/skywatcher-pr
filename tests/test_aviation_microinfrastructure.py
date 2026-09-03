import pytest

from skywatcher.core.aviation_microinfrastructure import (
    AviationMicrofacility,
    BindingState,
    GeometryState,
    HelipadEvidence,
    LandingSurfaceType,
    PhysicalClass,
    SpatialRelation,
    TerminalAssociation,
    can_promote_to_physical_helipad,
    classify_terminal_event,
)


def test_marked_h_supports_physical_helipad_without_operator_binding():
    pad = AviationMicrofacility(
        facility_id="SIG_WATERFRONT_HELIPAD_01",
        airfield_id="SIG_TJIG",
        physical_class=PhysicalClass.HELIPAD,
        facility_name_raw="visible circular H marking",
        operator_raw="AIR AMBULANCE LIFE FLIGHT...",
        operator_binding_state=BindingState.UNRESOLVED,
        landing_surface_geometry_state=GeometryState.OBSERVED_UNGEOREFERENCED,
        landing_surface_type=LandingSurfaceType.HELIPAD,
        helipad_evidence=HelipadEvidence.MARKED_H,
    )

    assert can_promote_to_physical_helipad(pad) is True
    assert pad.operator_id is None
    assert pad.operator_binding_state is BindingState.UNRESOLVED


def test_helicopter_presence_does_not_promote_hangar_to_helipad():
    hangar = AviationMicrofacility(
        facility_id="SIG_MODERN_WEST_HANGAR_01",
        airfield_id="SIG_TJIG",
        physical_class=PhysicalClass.HANGAR,
        facility_name_raw="Modern Aviation West Hangar POI area",
        rotor_activity_observed=True,
        landing_surface_type=LandingSurfaceType.NONE,
        helipad_evidence=HelipadEvidence.NONE,
    )

    assert can_promote_to_physical_helipad(hangar) is False


def test_non_aviation_adjacency_is_hard_negative_for_landing_surface():
    argos = AviationMicrofacility(
        facility_id="SIG_ARGOS_MARITIME_ADJACENCY_01",
        airfield_id="SIG_TJIG",
        physical_class=PhysicalClass.NON_AVIATION_ADJACENCY,
        facility_name_raw="Argos Puerto Rico Maritime Terminal POI area",
        landing_surface_type=LandingSurfaceType.NONE,
    )
    argos.validate()
    assert can_promote_to_physical_helipad(argos) is False


def test_non_aviation_adjacency_rejects_helipad_claim():
    bad = AviationMicrofacility(
        facility_id="BAD_ARGOS_LZ",
        airfield_id="SIG_TJIG",
        physical_class=PhysicalClass.NON_AVIATION_ADJACENCY,
        facility_name_raw="industrial adjacency",
        landing_surface_type=LandingSurfaceType.HELIPAD,
        helipad_evidence=HelipadEvidence.MARKED_H,
    )
    with pytest.raises(ValueError, match="non-aviation adjacency"):
        bad.validate()


def test_operator_id_cannot_exist_without_resolved_binding():
    bad = AviationMicrofacility(
        facility_id="BAD_OPERATOR_BINDING",
        airfield_id="SIG_TJIG",
        physical_class=PhysicalClass.HANGAR,
        facility_name_raw="candidate hangar",
        operator_id="some-operator",
        operator_binding_state=BindingState.UNRESOLVED,
    )
    with pytest.raises(ValueError, match="operator_id"):
        bad.validate()


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (
            SpatialRelation.LANDING_SURFACE_EXACT,
            TerminalAssociation.LANDING_SURFACE_ASSOCIATED,
        ),
        (
            SpatialRelation.LANDING_SURFACE_UNCERTAINTY,
            TerminalAssociation.LANDING_SURFACE_CANDIDATE,
        ),
        (SpatialRelation.APRON, TerminalAssociation.APRON_ARRIVAL),
        (
            SpatialRelation.FACILITY_COMPOUND,
            TerminalAssociation.FACILITY_ASSOCIATED_CANDIDATE,
        ),
        (SpatialRelation.NEAREST_ONLY, TerminalAssociation.DISCOVERY_ONLY),
        (SpatialRelation.OUTSIDE, TerminalAssociation.OUTSIDE),
        (SpatialRelation.UNRESOLVED, TerminalAssociation.UNRESOLVED),
    ],
)
def test_terminal_event_truth_ladder(relation, expected):
    assert classify_terminal_event(relation) is expected


def test_nearest_hangar_is_never_landing_or_identity_evidence():
    result = classify_terminal_event(SpatialRelation.NEAREST_ONLY)
    assert result is TerminalAssociation.DISCOVERY_ONLY
    assert result is not TerminalAssociation.LANDING_SURFACE_ASSOCIATED
    assert result is not TerminalAssociation.FACILITY_ASSOCIATED_CANDIDATE
