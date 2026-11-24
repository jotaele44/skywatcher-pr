"""Observer-frame ephemeris for the Sky Target Finder.

Thin, deterministic wrapper over astronomy-engine (MIT, Don Cross). Catalog
positions are J2000 (EQJ); one ``SkyFrame`` per request holds the EQJ->horizon
rotation for a time and observer, so thousands of stars are transformed with a
3x3 multiply each. Visibility windows for fixed objects use the closed-form
hour-angle solution (thread-safe; astronomy-engine's ``DefineStar`` mutates a
module-global table and is never called here). Sun, Moon and planets use the
library's searches. All times are timezone-aware UTC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import astronomy as ae

_J2000_UTC = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
# Solar days per sidereal day: converts hour angle to elapsed time.
_SOLAR_PER_SIDEREAL = 0.9972695717592592
# Standard rise/set altitude for a point source: -34 arcmin of horizon refraction.
RISE_SET_ALTITUDE_DEG = -34.0 / 60.0

SOLAR_SYSTEM_BODIES = (
    ("sun", "sun", "Sun", ae.Body.Sun),
    ("moon", "moon", "Moon", ae.Body.Moon),
    ("planet:mercury", "planet", "Mercury", ae.Body.Mercury),
    ("planet:venus", "planet", "Venus", ae.Body.Venus),
    ("planet:mars", "planet", "Mars", ae.Body.Mars),
    ("planet:jupiter", "planet", "Jupiter", ae.Body.Jupiter),
    ("planet:saturn", "planet", "Saturn", ae.Body.Saturn),
    ("planet:uranus", "planet", "Uranus", ae.Body.Uranus),
    ("planet:neptune", "planet", "Neptune", ae.Body.Neptune),
)


@dataclass(frozen=True)
class Observer:
    """A geodetic observing site (WGS-84 latitude/longitude, metres above sea level)."""

    lat_deg: float
    lon_deg: float
    elev_m: float = 0.0


@dataclass(frozen=True)
class Visibility:
    """Rise/set/transit state of a target relative to the observer's horizon."""

    state: str  # UP | DOWN | ALWAYS_UP | NEVER_UP
    rise: datetime | None = None
    set: datetime | None = None
    transit: datetime | None = None
    transit_alt_deg: float | None = None


def _engine_time(at: datetime) -> ae.Time:
    utc = at.astimezone(timezone.utc)
    return ae.Time.Make(
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second + utc.microsecond / 1e6
    )


def _datetime(time: ae.Time) -> datetime:
    # astronomy-engine 2.1.19's Time.Utc() is naive; derive an aware UTC value instead.
    return _J2000_UTC + timedelta(days=time.ut)


def _apparent(alt_deg: float) -> float:
    return alt_deg + ae.RefractionAngle(ae.Refraction.Normal, alt_deg)


def _unit(ra_deg: float, dec_deg: float) -> tuple[float, float, float]:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    cos_dec = math.cos(dec)
    return cos_dec * math.cos(ra), cos_dec * math.sin(ra), math.sin(dec)


class SkyFrame:
    """Time- and observer-specific transforms; build one per request."""

    def __init__(self, observer: Observer, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("SkyFrame needs a timezone-aware datetime")
        self.observer = observer
        self.at = at.astimezone(timezone.utc)
        self.time = _engine_time(self.at)
        self.engine_observer = ae.Observer(observer.lat_deg, observer.lon_deg, observer.elev_m)
        # RotationMatrix.rot is stored transposed: out_i = sum_j rot[j][i] * in_j.
        self._hor = ae.Rotation_EQJ_HOR(self.time, self.engine_observer).rot
        self._eqd = ae.Rotation_EQJ_EQD(self.time).rot
        self._gast_deg = ae.SiderealTime(self.time) * 15.0

    # -- J2000 <-> horizon -------------------------------------------------

    def horizontal(self, ra_deg: float, dec_deg: float) -> tuple[float, float, float]:
        """J2000 RA/Dec -> (apparent altitude, azimuth N->E, airless altitude), degrees."""
        x, y, z = _unit(ra_deg, dec_deg)
        m = self._hor
        north = m[0][0] * x + m[1][0] * y + m[2][0] * z
        west = m[0][1] * x + m[1][1] * y + m[2][1] * z
        up = m[0][2] * x + m[1][2] * y + m[2][2] * z
        alt = math.degrees(math.atan2(up, math.hypot(north, west)))
        az = math.degrees(math.atan2(-west, north)) % 360.0
        return _apparent(alt), az, alt

    def j2000_from_horizon_vector(
        self, north: float, west: float, up: float
    ) -> tuple[float, float]:
        """A topocentric horizon-frame direction -> J2000 (RA, Dec) in degrees."""
        m = self._hor
        x = m[0][0] * north + m[0][1] * west + m[0][2] * up
        y = m[1][0] * north + m[1][1] * west + m[1][2] * up
        z = m[2][0] * north + m[2][1] * west + m[2][2] * up
        norm = math.sqrt(x * x + y * y + z * z)
        ra = math.degrees(math.atan2(y, x)) % 360.0
        dec = math.degrees(math.asin(max(-1.0, min(1.0, z / norm))))
        return ra, dec

    # -- visibility ----------------------------------------------------------

    def fixed_visibility(
        self, ra_deg: float, dec_deg: float, h0_deg: float = RISE_SET_ALTITUDE_DEG
    ) -> Visibility:
        """Closed-form rise/set/transit for a fixed J2000 position (error of a few seconds)."""
        x, y, z = _unit(ra_deg, dec_deg)
        m = self._eqd
        xd = m[0][0] * x + m[1][0] * y + m[2][0] * z
        yd = m[0][1] * x + m[1][1] * y + m[2][1] * z
        zd = m[0][2] * x + m[1][2] * y + m[2][2] * z
        ra_d = math.degrees(math.atan2(yd, xd)) % 360.0
        dec_d = math.degrees(math.asin(max(-1.0, min(1.0, zd))))

        lat = self.observer.lat_deg
        phi, dec = math.radians(lat), math.radians(dec_d)
        transit_alt = _apparent(90.0 - abs(lat - dec_d))
        lst = (self._gast_deg + self.observer.lon_deg) % 360.0
        ha = ((lst - ra_d + 180.0) % 360.0) - 180.0  # (-180, 180]; + = west of meridian
        k = _SOLAR_PER_SIDEREAL / 360.0  # days per degree of hour angle

        def after(degrees: float) -> datetime:
            return self.at + timedelta(days=degrees * k)

        next_transit = after((-ha) % 360.0)
        denominator = math.cos(phi) * math.cos(dec)
        cos_h0 = (
            (math.sin(math.radians(h0_deg)) - math.sin(phi) * math.sin(dec)) / denominator
            if abs(denominator) > 1e-12
            else (-2.0 if lat * dec_d > 0 else 2.0)
        )
        if cos_h0 <= -1.0:
            return Visibility("ALWAYS_UP", None, None, next_transit, round(transit_alt, 2))
        if cos_h0 >= 1.0:
            return Visibility("NEVER_UP", None, None, next_transit, round(transit_alt, 2))
        semi_arc = math.degrees(math.acos(cos_h0))
        if abs(ha) < semi_arc:
            return Visibility(
                "UP",
                after(-(ha + semi_arc)),
                after(semi_arc - ha),
                after(-ha),
                round(transit_alt, 2),
            )
        rise_offset = (-semi_arc - ha) % 360.0
        return Visibility(
            "DOWN",
            after(rise_offset),
            after(rise_offset + 2.0 * semi_arc),
            after(rise_offset + semi_arc),
            round(transit_alt, 2),
        )


def _body_visibility(body: ae.Body, frame: SkyFrame, airless_alt: float) -> Visibility:
    obs, t = frame.engine_observer, frame.time
    culmination = ae.SearchHourAngle(body, obs, 0.0, t, +1)
    if airless_alt > RISE_SET_ALTITUDE_DEG:
        rise = ae.SearchRiseSet(body, obs, ae.Direction.Rise, t, -1.5)
        set_ = ae.SearchRiseSet(body, obs, ae.Direction.Set, t, 1.5)
        if rise is None and set_ is None:
            return Visibility("ALWAYS_UP", None, None, _datetime(culmination.time),
                              round(culmination.hor.altitude, 2))
        hour_angle = ae.HourAngle(body, t, obs)
        if hour_angle < 12.0:  # already past the meridian on this pass
            culmination = ae.SearchHourAngle(body, obs, 0.0, t, -1)
        return Visibility(
            "UP",
            _datetime(rise) if rise else None,
            _datetime(set_) if set_ else None,
            _datetime(culmination.time),
            round(culmination.hor.altitude, 2),
        )
    rise = ae.SearchRiseSet(body, obs, ae.Direction.Rise, t, 1.5)
    if rise is None:
        return Visibility("NEVER_UP", None, None, _datetime(culmination.time),
                          round(culmination.hor.altitude, 2))
    set_ = ae.SearchRiseSet(body, obs, ae.Direction.Set, rise, 1.5)
    culmination = ae.SearchHourAngle(body, obs, 0.0, rise, +1)
    return Visibility(
        "DOWN",
        _datetime(rise),
        _datetime(set_) if set_ else None,
        _datetime(culmination.time),
        round(culmination.hor.altitude, 2),
    )


@dataclass(frozen=True)
class BodyPosition:
    """Apparent topocentric position of a solar-system body."""

    id: str
    kind: str
    name: str
    ra_j2000_deg: float
    dec_j2000_deg: float
    alt_deg: float
    az_deg: float
    magnitude: float | None
    visibility: Visibility


@lru_cache(maxsize=64)
def _solar_system_cached(
    lat: float, lon: float, elev: float, at_iso: str
) -> tuple[BodyPosition, ...]:
    frame = SkyFrame(Observer(lat, lon, elev), datetime.fromisoformat(at_iso))
    out = []
    for body_id, kind, name, body in SOLAR_SYSTEM_BODIES:
        of_date = ae.Equator(body, frame.time, frame.engine_observer, True, True)
        airless = ae.Horizon(
            frame.time, frame.engine_observer, of_date.ra, of_date.dec, ae.Refraction.Airless
        )
        j2000 = ae.Equator(body, frame.time, frame.engine_observer, False, False)
        out.append(
            BodyPosition(
                id=body_id,
                kind=kind,
                name=name,
                ra_j2000_deg=round((j2000.ra * 15.0) % 360.0, 4),
                dec_j2000_deg=round(j2000.dec, 4),
                alt_deg=_apparent(airless.altitude),
                az_deg=airless.azimuth % 360.0,
                magnitude=round(ae.Illumination(body, frame.time).mag, 2),
                visibility=_body_visibility(body, frame, airless.altitude),
            )
        )
    return tuple(out)


def solar_system_positions(frame: SkyFrame) -> tuple[BodyPosition, ...]:
    """Sun, Moon and the planets as seen from the frame's observer (cached per minute)."""
    obs = frame.observer
    # Cached per whole minute: the Moon, the fastest body, moves under 0.01 deg in that time.
    minute = frame.at.replace(second=0, microsecond=0)
    return _solar_system_cached(
        round(obs.lat_deg, 4), round(obs.lon_deg, 4), round(obs.elev_m, 1), minute.isoformat()
    )


def solar_system_j2000(frame: SkyFrame) -> tuple[tuple[str, float, float], ...]:
    """(id, RA, Dec) J2000 of the Moon and planets at the frame time; positions only."""
    out = []
    for body_id, kind, _name, body in SOLAR_SYSTEM_BODIES:
        if kind == "sun":
            continue
        j2000 = ae.Equator(body, frame.time, frame.engine_observer, False, False)
        out.append((body_id, (j2000.ra * 15.0) % 360.0, j2000.dec))
    return tuple(out)


@lru_cache(maxsize=64)
def _dark_window_cached(
    lat: float, lon: float, elev: float, at_iso: str, sun_alt_deg: float
) -> tuple[datetime, datetime] | None:
    frame = SkyFrame(Observer(lat, lon, elev), datetime.fromisoformat(at_iso))
    obs, t = frame.engine_observer, frame.time
    sun = ae.Equator(ae.Body.Sun, t, obs, True, True)
    now_alt = ae.Horizon(t, obs, sun.ra, sun.dec, ae.Refraction.Airless).altitude
    if now_alt < sun_alt_deg:
        dusk = ae.SearchAltitude(ae.Body.Sun, obs, ae.Direction.Set, t, -1.5, sun_alt_deg)
    else:
        dusk = ae.SearchAltitude(ae.Body.Sun, obs, ae.Direction.Set, t, 1.5, sun_alt_deg)
    if dusk is None:
        return None
    dawn = ae.SearchAltitude(ae.Body.Sun, obs, ae.Direction.Rise, dusk, 1.5, sun_alt_deg)
    if dawn is None:
        return None
    return _datetime(dusk), _datetime(dawn)


def dark_window(frame: SkyFrame, sun_alt_deg: float = -12.0) -> tuple[datetime, datetime] | None:
    """The dark window (Sun below ``sun_alt_deg``) containing the frame time, else the next."""
    obs = frame.observer
    minute = frame.at.replace(second=0, microsecond=0)
    return _dark_window_cached(
        round(obs.lat_deg, 4),
        round(obs.lon_deg, 4),
        round(obs.elev_m, 1),
        minute.isoformat(),
        sun_alt_deg,
    )
