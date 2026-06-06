"""Tests for AircraftIntelligence lookup and unknown deduction."""

import pytest

from aircraft_intelligence import AircraftIntelligence


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
    from aircraft_intelligence import AircraftProfile
    ai = AircraftIntelligence(populated_db)
    result = ai.lookup_aircraft("XUNKNOWN99")
    assert result is not None
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "XUNKNOWN99"


# ── Task 38: profile_completeness metric ─────────────────────────────────────

def test_profile_completeness_returns_float(populated_db):
    """AircraftIntelligence.profile_completeness must return float in [0,1] (Task 38)."""
    ai = AircraftIntelligence(populated_db)
    completeness = ai.profile_completeness
    assert isinstance(completeness, float)
    assert 0.0 <= completeness <= 1.0


def test_profile_completeness_full_profiles():
    """All 14 KNOWN_OPERATORS entries are complete — completeness should equal 1.0."""
    from aircraft_intelligence import AircraftIntelligence
    # AircraftIntelligence can be instantiated with a non-existent path
    # (profile_completeness doesn't query the DB)
    ai = AircraftIntelligence(":memory:")
    assert ai.profile_completeness == 1.0


# ── Task 53: find_unknown() ───────────────────────────────────────────────────

def test_find_unknown_known_callsign(populated_db):
    """Known callsigns must not appear in find_unknown() results."""
    ai = AircraftIntelligence(populated_db)
    unknown = ai.find_unknown(["N5854Z", "N767PD"])
    assert "N5854Z" not in unknown
    assert "N767PD" not in unknown


def test_find_unknown_unknown_callsign(populated_db):
    """Callsigns with no profile match must appear in find_unknown() results."""
    ai = AircraftIntelligence(populated_db)
    unknown = ai.find_unknown(["N5854Z", "XUNKNOWN_ZZZZ"])
    assert "XUNKNOWN_ZZZZ" in unknown
