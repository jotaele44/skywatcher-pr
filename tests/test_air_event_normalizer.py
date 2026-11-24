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
