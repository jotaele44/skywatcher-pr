"""Observer-frame ephemeris checked against USNO values and geometric invariants.

External reference: USNO Astronomical Applications celestial-navigation and
sun/moon services for San Juan (18.4655 N, 66.1057 W). Hc/Zn are airless
altitude/azimuth of apparent positions; rise/set times are local (UTC-4) minutes.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import astronomy as ae
import pytest

from skywatcher.core.sky.catalog import load_catalog
from skywatcher.core.sky.ephemeris import (
    Observer,
    SkyFrame,
    dark_window,
    solar_system_positions,
)

SKY_DIR = Path(__file__).resolve().parents[1] / "data" / "reference" / "sky"
SAN_JUAN = Observer(18.4655, -66.1057, 0.0)
USNO_AT = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)


def _star(hip: int) -> tuple[float, float]:
    _, ra, dec, _ = next(row for row in load_catalog(SKY_DIR).stars if row[0] == hip)
    return ra, dec


def _azimuth_close(a: float, b: float, tolerance: float) -> bool:
    return abs(((a - b + 180.0) % 360.0) - 180.0) <= tolerance


def _within(actual: datetime | None, expected: datetime, minutes: float = 2.0) -> bool:
    return actual is not None and abs((actual - expected).total_seconds()) <= minutes * 60.0


@pytest.mark.parametrize(
    ("name", "hip", "hc", "zn"),
    [
        ("Deneb", 102098, 58.675486, 333.479793),
        ("Vega", 91262, 42.018192, 306.056741),
        ("Altair", 97649, 57.675130, 257.218013),
        ("Polaris", 11767, 18.601764, 0.643132),
    ],
)
def test_star_altitude_azimuth_match_usno(name, hip, hc, zn):
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    apparent, az, airless = frame.horizontal(*_star(hip))
    assert abs(airless - hc) <= 0.03, name
    assert _azimuth_close(az, zn, 0.03), name
    assert apparent > airless  # refraction lifts every object above the horizon


def test_sidereal_time_matches_usno_gha_aries():
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    assert abs(ae.SiderealTime(frame.time) * 15.0 - 35.99250852577059) <= 0.002


def test_saturn_matches_usno():
    saturn = next(b for b in solar_system_positions(SkyFrame(SAN_JUAN, USNO_AT))
                  if b.id == "planet:saturn")
    refraction = ae.RefractionAngle(ae.Refraction.Normal, 46.864835)
    assert abs(saturn.alt_deg - (46.864835 + refraction)) <= 0.05
    assert _azimuth_close(saturn.az_deg, 108.401094, 0.05)


def test_moon_includes_topocentric_parallax():
    # USNO Hc 49.773223 is geocentric; parallax at that altitude is ~0.5977 deg.
    moon = next(b for b in solar_system_positions(SkyFrame(SAN_JUAN, USNO_AT)) if b.id == "moon")
    expected = 49.773223 - 0.5977
    expected += ae.RefractionAngle(ae.Refraction.Normal, expected)
    assert abs(moon.alt_deg - expected) <= 0.05
    assert _azimuth_close(moon.az_deg, 203.147401, 0.1)


def test_sun_rise_and_set_match_usno():
    # 2026-10-19: sunrise 06:19, sunset 17:59 local (UTC-4).
    night = SkyFrame(SAN_JUAN, datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc))
    sun = next(b for b in solar_system_positions(night) if b.id == "sun")
    assert sun.visibility.state == "DOWN"
    assert _within(sun.visibility.rise, datetime(2026, 10, 19, 10, 19, tzinfo=timezone.utc))
    assert _within(sun.visibility.set, datetime(2026, 10, 19, 21, 59, tzinfo=timezone.utc))
    # 2026-06-21: sunrise 05:49, sunset 19:03 local; queried at local noon (Sun up).
    day = SkyFrame(SAN_JUAN, datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc))
    sun = next(b for b in solar_system_positions(day) if b.id == "sun")
    assert sun.visibility.state == "UP"
    assert _within(sun.visibility.rise, datetime(2026, 6, 21, 9, 49, tzinfo=timezone.utc))
    assert _within(sun.visibility.set, datetime(2026, 6, 21, 23, 3, tzinfo=timezone.utc))


def test_civil_twilight_window_matches_usno():
    # 2026-10-19 civil twilight ends 18:21 local; 2026-10-20 begins 05:58 local (USNO).
    frame = SkyFrame(SAN_JUAN, datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc))
    window = dark_window(frame, -6.0)
    assert window is not None
    assert _within(window[0], datetime(2026, 10, 19, 22, 21, tzinfo=timezone.utc))
    assert _within(window[1], datetime(2026, 10, 20, 9, 57, tzinfo=timezone.utc), minutes=3.0)


def test_dark_window_contains_a_dark_moment():
    frame = SkyFrame(SAN_JUAN, datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc))
    start, end = dark_window(frame, -12.0)
    assert start < frame.at < end


def test_polaris_altitude_tracks_latitude():
    for hour in range(0, 24, 6):
        frame = SkyFrame(SAN_JUAN, USNO_AT + timedelta(hours=hour))
        _, _, airless = frame.horizontal(*_star(11767))
        assert abs(airless - SAN_JUAN.lat_deg) < 1.0


def test_matrix_path_equals_library_horizon_path():
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    ra, dec = _star(102098)
    _, az, airless = frame.horizontal(ra, dec)
    vector = ae.VectorFromSphere(ae.Spherical(dec, ra, 1.0), frame.time)
    of_date = ae.EquatorFromVector(ae.RotateVector(ae.Rotation_EQJ_EQD(frame.time), vector))
    reference = ae.Horizon(
        frame.time, frame.engine_observer, of_date.ra, of_date.dec, ae.Refraction.Airless
    )
    assert abs(airless - reference.altitude) < 1e-6
    assert _azimuth_close(az, reference.azimuth, 1e-6)


def test_horizon_vector_round_trips_to_j2000():
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    ra, dec = _star(97649)
    _, az, alt = frame.horizontal(ra, dec)
    a, z = math.radians(alt), math.radians(az)
    back = frame.j2000_from_horizon_vector(
        math.cos(a) * math.cos(z), -math.cos(a) * math.sin(z), math.sin(a)
    )
    assert abs(back[0] - ra) < 1e-6 and abs(back[1] - dec) < 1e-6


def test_closed_form_window_agrees_with_library_search():
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    ra, dec = _star(102098)
    visibility = frame.fixed_visibility(ra, dec)
    assert visibility.state == "UP"
    ae.DefineStar(ae.Body.Star1, ra / 15.0, dec, 1000.0)
    searched_set = ae.SearchRiseSet(
        ae.Body.Star1, frame.engine_observer, ae.Direction.Set, frame.time, 1.0
    )
    searched_rise = ae.SearchRiseSet(
        ae.Body.Star1, frame.engine_observer, ae.Direction.Rise, frame.time, -1.0
    )
    j2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    assert abs((visibility.set - (j2000 + timedelta(days=searched_set.ut))).total_seconds()) < 30
    assert abs((visibility.rise - (j2000 + timedelta(days=searched_rise.ut))).total_seconds()) < 30
    assert visibility.rise < visibility.transit < visibility.set


def test_circumpolar_and_never_rising_states():
    frame = SkyFrame(SAN_JUAN, USNO_AT)
    assert frame.fixed_visibility(37.95, 89.26).state == "ALWAYS_UP"  # Polaris
    assert frame.fixed_visibility(95.99, -80.0).state == "NEVER_UP"


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        SkyFrame(SAN_JUAN, datetime(2026, 10, 20, 0, 30))
