from skywatcher.normalizers.air_event_normalizer import normalize_air_event
from skywatcher.fusion.cross_domain_overlap import find_cross_domain_overlaps


def test_air_event_output_has_required_policy_metadata():
    event = normalize_air_event({
        "tail": "N407PR",
        "timestamp": "2026-01-01T12:00:00+00:00",
        "lat": 18.44,
        "lon": -66.00,
    })

    assert event["tactical_public_tracking"] is False
    assert event["source_tier"] in {"T1", "T2", "T3", "T4"}
    assert event["mode"] in {"delayed_or_rate_limited", "batch_file"}
    assert "confidence" in event


def test_overlap_suppresses_disallowed_air_records():
    overlaps = find_cross_domain_overlaps(
        [{
            "event_id": "air_1",
            "observed_at": "2026-01-01T12:00:00+00:00",
            "lat": 18.45,
            "lon": -66.09,
            "tactical_public_tracking": True,
        }],
        [{
            "record_id": "ctx_1",
            "observed_at": "2026-01-01T12:00:00+00:00",
            "lat": 18.45,
            "lon": -66.09,
            "operational_use_allowed": False,
        }],
    )

    assert overlaps == []
