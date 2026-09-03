"""Equivalence/regression test for FPIM's POI-tracing responsibility: a POI is
any geographical point, natural or manmade, of interest to humans, regardless
of its actual correlation to the aircraft. FPIM enumerates every POI along or
near a flight path via skywatcher.correlation.footprint_proximity — this was
reclassified from CORRIM into FPIM during the module reorg (a pure static
gazetteer-vs-point match, no SATIM imagery involved). Enumeration must be
exhaustive and unfiltered, never gated by callsign/operator/mission label.
See docs/MODULE_SPEC_FPIM.md."""

from skywatcher.correlation.footprint_proximity import (
    AirspaceFootprint,
    correlate_point_to_footprints,
    matches_as_dicts,
)

HELIPAD = AirspaceFootprint(
    footprint_id="fp-1",
    airfield_code="TEST1",
    facility_name="Test Helipad",
    facility_type="helipad",
    operator_class="private",
    latitude=18.40,
    longitude=-66.10,
    radius_m=2000,
    confidence="high",
    source_tier="T1",
    description="",
)


def test_poi_enumeration_is_unconditional_and_unfiltered():
    # A point ~1.5km from the footprint should match regardless of any
    # aircraft label — correlate_point_to_footprints takes only lat/lon.
    matches = correlate_point_to_footprints(18.41, -66.10, [HELIPAD])
    assert len(matches) == 1
    assert matches[0].footprint_id == "fp-1"

    as_dicts = matches_as_dicts(matches)
    assert as_dicts[0]["facility_type"] == "helipad"


def test_poi_enumeration_empty_when_nothing_nearby():
    # Enumeration is exhaustive but not invented: no match -> empty list, not
    # a fabricated "unknown" placeholder.
    matches = correlate_point_to_footprints(0.0, 0.0, [HELIPAD])
    assert matches == []
