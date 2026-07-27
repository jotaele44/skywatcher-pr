"""Tests for exact aircraft identity lookup without mission inference."""

from aircraft_intelligence import AircraftIntelligence, AircraftProfile


def test_lookup_known_identifier_is_retained_but_unverified(populated_db):
    result = AircraftIntelligence(populated_db).lookup_aircraft("N5854Z")
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "N5854Z"
    assert result.data_source == "unverified_registry"
    assert result.primary_mission == "Unknown"
    assert result.secondary_missions == []
    assert result.operational_patterns == {}


def test_lookup_unknown_callsign_returns_profile(populated_db):
    result = AircraftIntelligence(populated_db).lookup_aircraft("ZZZZZ")
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "ZZZZZ"
    assert result.primary_mission == "Unknown"


def test_compile_report_disclaims_role_inference(populated_db):
    report = AircraftIntelligence(populated_db).compile_intelligence_report("N5854Z")
    assert "Role: Unknown (not inferred)" in report
    assert "high activity" not in report.lower()
    assert "operating hours" not in report.lower()


def test_partial_identifier_does_not_match_registry(populated_db):
    result = AircraftIntelligence(populated_db).lookup_aircraft("N5854")
    assert result.data_source == "observed_history"


def test_profile_completeness_requires_field_provenance(populated_db):
    completeness = AircraftIntelligence(populated_db).profile_completeness
    assert isinstance(completeness, float)
    assert completeness == 0.0


def test_find_unknown_uses_exact_normalized_identifier(populated_db):
    intelligence = AircraftIntelligence(populated_db)
    assert intelligence.find_unknown(["N5854Z", "N767PD"]) == []
    assert intelligence.find_unknown(["N5854", "XUNKNOWN_ZZZZ"]) == [
        "N5854",
        "XUNKNOWN_ZZZZ",
    ]
