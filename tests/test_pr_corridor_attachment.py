from skywatcher.fusion.coastal_corridor_index import attach_corridor


def test_attach_corridor_matches_regional_zone():
    event = attach_corridor({"lat": 18.45, "lon": -66.09})

    assert event["corridor_id"] == "sj_corridor"
    assert event["corridor_distance_km"] < 5


def test_attach_corridor_returns_none_outside_radius():
    event = attach_corridor({"lat": 17.0, "lon": -70.0})

    assert event["corridor_id"] is None


import math

import pytest

from skywatcher.fusion.coastal_corridor_index import haversine_km


@pytest.mark.parametrize("value", [None, True, "NaN", float("inf"), {}, "bad"])
def test_invalid_coordinates_cannot_become_candidates(value):
    with pytest.raises(ValueError):
        attach_corridor({"lat": value, "lon": -66.0})


def test_missing_coordinates_fail_closed():
    with pytest.raises(ValueError):
        attach_corridor({})


def test_tied_corridors_preserve_candidates_without_binding():
    corridors = [
        {"corridor_id": name, "name": name, "center_lat": 18, "center_lon": -66, "radius_km": 5}
        for name in ("a", "b")
    ]
    result = attach_corridor({"lat": 18, "lon": -66}, corridors)
    assert result["corridor_id"] is None
    assert result["corridor_status"] == "UNRESOLVED"
    assert len(result["corridor_candidates"]) == 2
    assert result["identity_effect"] == "NONE"


def test_containing_corridor_not_hidden_by_nearer_outside_corridor():
    corridors = [
        {"corridor_id": "outside", "name": "Outside", "center_lat": 18.01, "center_lon": -66, "radius_km": 0.1},
        {"corridor_id": "inside", "name": "Inside", "center_lat": 18.02, "center_lon": -66, "radius_km": 5},
    ]
    result = attach_corridor({"lat": 18, "lon": -66}, corridors)
    assert result["corridor_id"] == "inside"
    assert result["corridor_status"] == "CANDIDATE_NOT_IDENTITY"


def test_empty_corridors_are_json_safe():
    assert attach_corridor({"lat": 18, "lon": -66}, [])['corridor_distance_km'] is None


def test_antipodal_distance_is_finite():
    assert math.isfinite(haversine_km(18, -66, -18, 114))


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (-91, 0)])
def test_out_of_range_coordinates_are_rejected(lat, lon):
    with pytest.raises(ValueError):
        haversine_km(lat, lon, 0, 0)
