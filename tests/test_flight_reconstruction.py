"""Gate: flight reconstruction from synthetic observations."""

from __future__ import annotations

from skywatcher.fr24 import flight_reconstruction as fr


def _row(reg, ts, lat, lon, alt):
    return {
        "registration": reg,
        "callsign_or_label": reg,
        "image_name": f"{reg}_{ts}.png",
        "timestamp": ts,
        "lat": lat,
        "lon": lon,
        "barometric_altitude_ft": alt,
        "confidence": 0.7,
    }


def test_aircraft_identity_prefers_registration():
    assert fr.aircraft_identity(_row("N123", "2026-01-01T00:00:00", 18.1, -66.0, 3000)) == "N123"


def test_reconstruct_single_flight_from_two_frames():
    rows = [
        _row("N123", "2026-01-01T00:00:00", 18.1, -66.0, 3000),
        _row("N123", "2026-01-01T00:05:00", 18.2, -66.1, 3200),
    ]
    flights = fr.reconstruct_flights(rows)
    assert len(flights) == 1
    rec = flights[0]
    assert rec["num_screenshots"] == 2
    assert len(rec["points"]) == 2
    assert rec["max_altitude_ft"] == 3200
    assert rec["confirmation_status"] == "not_confirmed"


def test_two_aircraft_reconstruct_separately():
    rows = [
        _row("N123", "2026-01-01T00:00:00", 18.1, -66.0, 3000),
        _row("N999", "2026-01-01T00:01:00", 18.5, -66.5, 5000),
    ]
    flights = fr.reconstruct_flights(rows)
    assert len(flights) == 2


def test_build_track_points_caps_count():
    pts = list(range(10))
    sampled = fr.build_track_points(pts, max_points=3)
    assert len(sampled) <= 3
