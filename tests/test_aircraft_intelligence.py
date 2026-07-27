"""Tests for exact aircraft identity lookup without mission inference."""

from aircraft_intelligence import AircraftIntelligence, AircraftProfile
from skywatcher.core.known_operators import KNOWN_OPERATORS

COMPLETE_PROVENANCE = {
    "source_uri": "https://example.test/registry",
    "source_record_id": "record-1",
    "captured_at": "2026-07-27T20:00:00Z",
    "sha256": "a" * 64,
}


def test_lookup_known_identifier_is_retained_but_unverified(populated_db):
    result = AircraftIntelligence(populated_db).lookup_aircraft("N5854Z")
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "N5854Z"
    assert result.data_source == "unverified_registry"
    assert result.aircraft_type == ""
    assert result.owner == "Unknown"
    assert result.operator == "Unknown"
    assert result.primary_mission == "Unknown"
    assert result.secondary_missions == []
    assert result.operational_patterns == {}
    assert result.total_flights == 1


def test_incomplete_provenance_keeps_identity_inactive(monkeypatch, tmp_path):
    monkeypatch.setitem(
        KNOWN_OPERATORS,
        "NPROV1",
        {
            "identifier": "NPROV1",
            "verified_fields": {
                "aircraft_type": "Test Type",
                "owner": "Unproven Owner",
                "operator": "Unproven Operator",
            },
            "provenance": {
                **COMPLETE_PROVENANCE,
                "sha256": None,
            },
        },
    )
    result = AircraftIntelligence(str(tmp_path / "none.sqlite")).lookup_aircraft("NPROV1")
    assert result.data_source == "unverified_registry"
    assert result.aircraft_type == ""
    assert result.owner == "Unknown"
    assert result.operator == "Unknown"


def test_complete_field_provenance_activates_only_supported_fields(monkeypatch, tmp_path):
    monkeypatch.setitem(
        KNOWN_OPERATORS,
        "NPROV2",
        {
            "identifier": "NPROV2",
            "verified_fields": {
                "aircraft_type": "Verified Type",
                "owner": "Verified Owner",
                "operator": "Still Unproven",
                "primary_mission": "Must Never Activate",
            },
            "field_provenance": {
                "aircraft_type": COMPLETE_PROVENANCE,
                "owner": {**COMPLETE_PROVENANCE, "source_record_id": "owner-record"},
                "operator": {**COMPLETE_PROVENANCE, "captured_at": None},
                "primary_mission": COMPLETE_PROVENANCE,
            },
        },
    )
    result = AircraftIntelligence(str(tmp_path / "none.sqlite")).lookup_aircraft("NPROV2")
    assert result.data_source == "verified_registry"
    assert result.aircraft_type == "Verified Type"
    assert result.owner == "Verified Owner"
    assert result.operator == "Unknown"
    assert result.primary_mission == "Unknown"
    assert set(result.provenance["fields"]) == {"aircraft_type", "owner"}


def test_lookup_unknown_callsign_returns_profile(populated_db):
    result = AircraftIntelligence(populated_db).lookup_aircraft("ZZZZZ")
    assert isinstance(result, AircraftProfile)
    assert result.callsign == "ZZZZZ"
    assert result.primary_mission == "Unknown"


def test_compile_report_disclaims_role_and_omits_unproven_identity(populated_db):
    report = AircraftIntelligence(populated_db).compile_intelligence_report("N5854Z")
    assert "Role: Unknown (not inferred)" in report
    assert "Aircraft Type: Unknown" in report
    assert "Owner: Unknown" in report
    assert "Operator: Unknown" in report
    assert "Puerto Rico Electric Power Authority" not in report
    assert "H125" not in report
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
