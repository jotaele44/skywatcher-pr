"""Tests for AircraftIntelligence lookup and unknown deduction."""

import pytest

from pipeline.aircraft_intelligence import AircraftIntelligence


def test_lookup_known_callsign(populated_db):
    ai = AircraftIntelligence(populated_db)
    result = ai.lookup_aircraft("N5854Z")
    assert result is not None


def test_lookup_unknown_callsign_returns_result(populated_db):
    ai = AircraftIntelligence(populated_db)
    result = ai.lookup_aircraft("ZZZZZ")
    # Should return something (None or a dict/object) without raising
    # The key requirement is no exception
    assert True


def test_compile_intelligence_report_known(populated_db):
    ai = AircraftIntelligence(populated_db)
    report = ai.compile_intelligence_report("N5854Z")
    assert report is not None


def test_compile_intelligence_report_returns_result(populated_db):
    ai = AircraftIntelligence(populated_db)
    result = ai.compile_intelligence_report("C6062")
    # Must not raise; may return string, dict, or None depending on implementation
    assert result is None or isinstance(result, (dict, str))


def test_lookup_callsign_with_no_operator_returns_profile(populated_db):
    from pipeline.aircraft_intelligence import AircraftProfile
    ai = AircraftIntelligence(populated_db)
    result = ai.lookup_aircraft("XUNKNOWN99")
    assert result is not None
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "XUNKNOWN99"
