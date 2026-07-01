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
