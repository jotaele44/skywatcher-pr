"""Golden regression gates derived from the N5854Z Tres Monjitas screenshots.

The fixture encodes only observations that are visible in the supplied
screenshots.  It intentionally does not encode exact coordinates, true AGL,
landing, facility target, or exact mission because those remain unresolved.
"""
from fr24.behavior_truth import (
    AltitudeState,
    AssociationState,
    Certification,
    LandingState,
    MotionState,
    assess_baro_altitude,
    assess_landing,
    assess_site_association,
    mission_family_from_context,
)


def test_n5854z_zero_baro_does_not_become_ground_state() -> None:
    for speed in (18.0, 29.0, 30.0):
        result = assess_baro_altitude(
            0.0,
            ground_speed_mph=speed,
            rendered_track_crosses_non_ground_surface=True,
        )
        assert result.state is AltitudeState.CONTRADICTED
        assert result.certification is Certification.PASS


def test_n5854z_stationary_endpoint_is_landing_candidate_not_fact() -> None:
    result = assess_landing(
        (18.0, 29.0, 30.0, 0.0),
        stationary_samples=2,
        independent_ground_contact=False,
        later_departure_same_position=False,
    )
    assert result.motion_state is MotionState.HOVER_OR_GROUND_UNRESOLVED
    assert result.landing_state is LandingState.CANDIDATE
    assert result.certification is Certification.PROVISIONAL


def test_n5854z_landing_can_only_promote_with_independent_evidence() -> None:
    result = assess_landing(
        (30.0, 0.0),
        stationary_samples=2,
        independent_ground_contact=True,
    )
    assert result.landing_state is LandingState.CERTIFIED
    assert result.certification is Certification.PASS


def test_cee_label_and_proximity_cannot_become_target_identity() -> None:
    result = assess_site_association(
        proximity_only=True,
        independent_site_binding=False,
        corridor_alignment_supported=False,
    )
    assert result.state is AssociationState.NO_SITE_ASSOCIATION_PROVEN
    assert result.certification is Certification.CANDIDATE_NOT_IDENTITY


def test_power_corridor_alignment_stays_association_not_target() -> None:
    result = assess_site_association(
        proximity_only=True,
        independent_site_binding=False,
        corridor_alignment_supported=True,
    )
    assert result.state is AssociationState.LINEAR_INFRASTRUCTURE_ALIGNED
    assert result.certification is Certification.PROVISIONAL


def test_utility_context_only_yields_provisional_mission_family() -> None:
    mission, cert = mission_family_from_context(
        owner_or_operator_utility_context=True,
        corridor_alignment_supported=True,
        independent_mission_record=False,
    )
    assert mission == "UTILITY_INSPECTION_OR_MAINTENANCE_FAMILY"
    assert cert is Certification.PROVISIONAL


def test_independent_mission_record_is_required_for_mission_pass() -> None:
    mission, cert = mission_family_from_context(
        owner_or_operator_utility_context=True,
        corridor_alignment_supported=True,
        independent_mission_record=True,
    )
    assert mission == "UTILITY_MISSION_SUPPORTED"
    assert cert is Certification.PASS
