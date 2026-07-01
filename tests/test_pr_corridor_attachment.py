from skywatcher.fusion.coastal_corridor_index import attach_corridor


def test_attach_corridor_matches_regional_zone():
    event = attach_corridor({"lat": 18.45, "lon": -66.09})

    assert event["corridor_id"] == "sj_corridor"
    assert event["corridor_distance_km"] < 5


def test_attach_corridor_returns_none_outside_radius():
    event = attach_corridor({"lat": 17.0, "lon": -70.0})

    assert event["corridor_id"] is None
