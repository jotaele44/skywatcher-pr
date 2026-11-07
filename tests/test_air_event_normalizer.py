import json
from pathlib import Path

from jsonschema import Draft202012Validator

from skywatcher.normalizers.air_event_normalizer import normalize_air_event


def test_normalize_air_event_forces_guardrails_and_ids():
    event = normalize_air_event({
        "tail": "N407PR",
        "timestamp": "2026-01-01T12:00:00+00:00",
        "lat": 18.44,
        "lon": -66.00,
        "altitude_ft": "1200",
        "speed_kt": "95",
        "heading_deg": "180",
    })

    assert event["event_id"].startswith("air_")
    assert event["callsign"] == "N407PR"
    assert event["source_tier"] == "T2"
    assert event["mode"] == "batch_file"
    assert event["tactical_public_tracking"] is False
    assert 0 <= event["confidence"] <= 1



def test_normalize_air_event_preserves_separate_source_identity_dimensions():
    event = normalize_air_event(
        {
            "registration": "N600UH",
            "callsign": "C6062",
            "hex": "A7C001",
            "aircraft_type": "C172",
            "timestamp": "2026-09-09T12:00:00Z",
            "lat": 18.45,
            "lon": -66.10,
        }
    )

    assert event["aircraft_id"] == "A7C001"
    assert event["registration"] == "N600UH"
    assert event["callsign"] == "C6062"
    assert event["icao24"] == "A7C001"
    assert event["aircraft_type"] == "C172"
    assert event["source_identity"] == {
        "callsign": "C6062",
        "registration": "N600UH",
        "icao24": "A7C001",
        "aircraft_type": "C172",
    }
    assert event["identity_state"] == "SOURCE_IDENTITY_PRESENT"


def test_blank_source_callsign_uses_legacy_display_fallback_without_erasing_provenance():
    event = normalize_air_event(
        {
            "registration": "N600UH",
            "callsign": "",
            "timestamp": "2026-09-09T12:00:00Z",
            "lat": 18.45,
            "lon": -66.10,
        }
    )

    assert event["registration"] == "N600UH"
    assert event["callsign"] == "N600UH"
    assert event["source_identity"]["callsign"] is None
    assert event["source_identity"]["registration"] == "N600UH"


def test_missing_coordinates_remain_unknown_and_preserve_raw_values():
    event = normalize_air_event(
        {
            "tail": "N407PR",
            "timestamp": "2026-01-01T12:00:00+00:00",
            "lat": "",
            "longitude": None,
        }
    )

    assert event["lat"] is None
    assert event["lon"] is None
    assert event["geometry_status"] == "UNRESOLVED"
    assert event["coordinate_status"] == {"lat": "MISSING", "lon": "MISSING"}
    assert event["source_coordinates"]["lat_raw"] == ""
    assert event["source_coordinates"]["longitude_raw"] is None
    assert (event["lat"], event["lon"]) != (0.0, 0.0)


def test_invalid_coordinate_does_not_fall_through_to_secondary_field():
    event = normalize_air_event(
        {
            "tail": "N407PR",
            "timestamp": "2026-01-01T12:00:00+00:00",
            "lat": "not-a-coordinate",
            "latitude": 18.44,
            "lon": -66.0,
        }
    )

    assert event["lat"] is None
    assert event["lon"] == -66.0
    assert event["geometry_status"] == "INVALID"
    assert event["coordinate_status"]["lat"] == "INVALID"
    assert event["source_coordinates"]["selected_lat_field"] == "lat"
    assert event["source_coordinates"]["lat_raw"] == "not-a-coordinate"
    assert event["source_coordinates"]["latitude_raw"] == 18.44


def test_legitimate_zero_coordinate_is_preserved_not_treated_as_missing():
    event = normalize_air_event(
        {
            "tail": "N407PR",
            "timestamp": "2026-01-01T12:00:00+00:00",
            "lat": 0,
            "latitude": 18.44,
            "lon": 0,
            "longitude": -66.0,
        }
    )

    assert event["lat"] == 0.0
    assert event["lon"] == 0.0
    assert event["geometry_status"] == "LOCATED"
    assert event["source_coordinates"]["selected_lat_field"] == "lat"
    assert event["source_coordinates"]["selected_lon_field"] == "lon"


def test_air_event_v2_schema_accepts_unknown_geometry_without_zero_sentinel():
    event = normalize_air_event(
        {
            "tail": "N407PR",
            "timestamp": "2026-01-01T12:00:00+00:00",
        }
    )
    schema = json.loads(Path("schemas/air_event_v2.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(event)
    assert event["geometry_status"] == "UNRESOLVED"
    assert event["lat"] is None and event["lon"] is None
