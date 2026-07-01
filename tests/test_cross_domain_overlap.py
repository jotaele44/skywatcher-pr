from skywatcher.fusion.cross_domain_overlap import find_cross_domain_overlaps


def test_find_cross_domain_overlaps_emits_non_operational_candidate():
    air = [{
        "event_id": "air_1",
        "observed_at": "2026-01-01T12:00:00+00:00",
        "lat": 18.45,
        "lon": -66.09,
        "corridor_id": "sj_corridor",
        "tactical_public_tracking": False,
    }]
    context = [{
        "record_id": "ctx_1",
        "observed_at": "2026-01-01T12:30:00+00:00",
        "lat": 18.46,
        "lon": -66.10,
        "corridor_id": "sj_corridor",
        "operational_use_allowed": False,
    }]

    overlaps = find_cross_domain_overlaps(air, context)

    assert len(overlaps) == 1
    assert overlaps[0]["air_event_ids"] == ["air_1"]
    assert overlaps[0]["maritime_record_ids"] == ["ctx_1"]
    assert "not an operational cue" in overlaps[0]["explanation"]


def test_find_cross_domain_overlaps_suppresses_operational_context():
    overlaps = find_cross_domain_overlaps(
        [{"event_id": "air_1", "observed_at": "2026-01-01T12:00:00+00:00", "lat": 18.45, "lon": -66.09, "tactical_public_tracking": False}],
        [{"record_id": "ctx_1", "observed_at": "2026-01-01T12:00:00+00:00", "lat": 18.45, "lon": -66.09, "operational_use_allowed": True}],
    )

    assert overlaps == []
