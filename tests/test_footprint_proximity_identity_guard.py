from __future__ import annotations

from skywatcher.correlation.footprint_proximity import (
    correlate_point_to_footprints,
    matches_as_dicts,
)
from skywatcher.registry.airspace_footprints import AirspaceFootprint


def test_proximity_match_is_explicitly_candidate_not_identity() -> None:
    footprint = AirspaceFootprint(
        footprint_id="h1",
        airfield_code="TJIG",
        facility_name="Example Helipad",
        facility_type="helipad",
        operator_class="unknown",
        latitude=18.45,
        longitude=-66.09,
        radius_m=1000,
        confidence="candidate",
        source_tier="T3",
        description="fixture",
    )
    matches = correlate_point_to_footprints(18.45, -66.09, [footprint])
    assert len(matches) == 1
    match = matches[0]
    assert match.score == 1.0
    assert match.evidence_role == "DISCOVERY_ONLY"
    assert match.identity_state == "CANDIDATE_NOT_IDENTITY"

    row = matches_as_dicts(matches)[0]
    assert row["evidence_role"] == "DISCOVERY_ONLY"
    assert row["identity_state"] == "CANDIDATE_NOT_IDENTITY"
