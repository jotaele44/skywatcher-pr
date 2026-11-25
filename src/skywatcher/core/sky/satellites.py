"""Space-Track satellites as Sky Target Finder targets (SGP4 over frozen GP elements).

Reads only the locally frozen ``space_objects`` materialization (each object's
``gp_row["raw"]`` is the verbatim Space-Track OMM JSON row); it never calls
Space-Track. Propagation uses sgp4 (MIT, Brandon Rhodes) in the TEME frame;
TEME -> Earth-fixed uses IAU-82 GMST with polar motion ignored (under 1 arcsec),
the observer is WGS-84, and the topocentric direction is expressed in J2000 by
the same horizon rotation the star layer uses, so satellites and stars align.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import astronomy as ae
from sgp4 import omm
from sgp4.api import SGP4_ERRORS, WGS72, Satrec, jday

from .ephemeris import SkyFrame

_REQUIRED_FIELDS = (
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
    "NORAD_CAT_ID",
)
_WGS84_A_KM = 6378.137
_WGS84_F = 1.0 / 298.257223563
_EARTH_RADIUS_KM = 6378.137
_J2000_JD = 2451545.0
_J2000_UTC = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
# SGP4 drifts by kilometres per day; elements older than this are not propagated.
MAX_ELEMENT_AGE_DAYS = 30.0
_MALFORMED_ROW = "GP row rejected by sgp4: malformed element values"


class GPElementError(ValueError):
    """A GP/OMM row cannot be propagated (missing fields or an SGP4 error)."""


def _normalize_epoch(value: Any) -> str:
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." not in text:
        text += ".000000"
    head, fraction = text.split(".", 1)
    return f"{head}.{fraction[:6]}"


def _sgp4_reason(code: int) -> str:
    return SGP4_ERRORS.get(code, f"sgp4 error {code}")


# Skip reasons are served to API clients, so they are built from fixed text, field names
# and sgp4's error-code table only, never from exception messages.
def _build_satrec(raw: dict[str, Any]) -> tuple[Satrec | None, str | None]:
    missing = [key for key in _REQUIRED_FIELDS if raw.get(key) in (None, "")]
    if missing:
        return None, f"GP row missing {', '.join(missing)}"
    fields = {key: str(raw[key]) for key in _REQUIRED_FIELDS}
    fields["EPOCH"] = _normalize_epoch(raw["EPOCH"])
    # sgp4 2.27's OMM reader indexes these unconditionally; supply neutral defaults.
    fields["CLASSIFICATION_TYPE"] = str(raw.get("CLASSIFICATION_TYPE") or "U")
    fields["OBJECT_ID"] = str(raw.get("OBJECT_ID") or "")
    fields["EPHEMERIS_TYPE"] = str(raw.get("EPHEMERIS_TYPE") or "0")
    fields["ELEMENT_SET_NO"] = str(raw.get("ELEMENT_SET_NO") or "999")
    fields["REV_AT_EPOCH"] = str(raw.get("REV_AT_EPOCH") or "0")
    satellite = Satrec()
    try:
        omm.initialize(satellite, fields, WGS72)
    except (KeyError, TypeError, ValueError):
        return None, _MALFORMED_ROW
    if satellite.error:
        return None, _sgp4_reason(satellite.error)
    return satellite, None


def satrec_from_gp_raw(raw: dict[str, Any]) -> Satrec:
    """Build an SGP4 satellite record from a Space-Track GP (OMM JSON) row."""
    satellite, problem = _build_satrec(raw)
    if satellite is None:
        raise GPElementError(problem or _MALFORMED_ROW)
    return satellite


def gmst_radians(jd: float, fraction: float) -> float:
    """IAU-82 Greenwich mean sidereal time (Vallado gstime), radians."""
    t = (jd + fraction - _J2000_JD) / 36525.0
    seconds = (
        -6.2e-6 * t * t * t
        + 0.093104 * t * t
        + (876600.0 * 3600.0 + 8640184.812866) * t
        + 67310.54841
    )
    return math.radians((seconds / 240.0) % 360.0)


def _observer_ecef(lat_deg: float, lon_deg: float, elev_m: float) -> tuple[float, float, float]:
    lat, lon, h = math.radians(lat_deg), math.radians(lon_deg), elev_m / 1000.0
    e2 = _WGS84_F * (2.0 - _WGS84_F)
    n = _WGS84_A_KM / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    return (
        (n + h) * math.cos(lat) * math.cos(lon),
        (n + h) * math.cos(lat) * math.sin(lon),
        (n * (1.0 - e2) + h) * math.sin(lat),
    )


@dataclass(frozen=True)
class SatellitePosition:
    """Topocentric position of a satellite at the frame time."""

    alt_deg: float  # apparent (refracted)
    airless_alt_deg: float
    az_deg: float
    range_km: float
    ra_j2000_deg: float
    dec_j2000_deg: float
    sunlit: bool
    element_epoch: datetime
    element_age_days: float


def sun_direction(frame: SkyFrame) -> tuple[float, float, float]:
    """Geocentric unit vector towards the Sun at the frame time (J2000 axes)."""
    sun = ae.GeoVector(ae.Body.Sun, frame.time, True)
    norm = math.sqrt(sun.x * sun.x + sun.y * sun.y + sun.z * sun.z)
    return sun.x / norm, sun.y / norm, sun.z / norm


def topocentric(
    satellite: Satrec, frame: SkyFrame, sun_unit: tuple[float, float, float] | None = None
) -> SatellitePosition:
    """Propagate to the frame time and return the observer-relative position."""
    position, problem = propagate(satellite, frame, sun_unit)
    if position is None:
        raise GPElementError(problem or "sgp4 propagation failed")
    return position


def propagate(
    satellite: Satrec, frame: SkyFrame, sun_unit: tuple[float, float, float] | None = None
) -> tuple[SatellitePosition | None, str | None]:
    """Like ``topocentric`` but returns (None, reason) instead of raising on an SGP4 error."""
    at = frame.at
    jd, fraction = jday(at.year, at.month, at.day, at.hour, at.minute,
                        at.second + at.microsecond * 1e-6)
    error, position, _velocity = satellite.sgp4(jd, fraction)
    if error != 0:
        return None, _sgp4_reason(error)
    x, y, z = position  # TEME, km

    theta = gmst_radians(jd, fraction)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    xe, ye, ze = cos_t * x + sin_t * y, -sin_t * x + cos_t * y, z
    obs = frame.observer
    ox, oy, oz = _observer_ecef(obs.lat_deg, obs.lon_deg, obs.elev_m)
    rx, ry, rz = xe - ox, ye - oy, ze - oz
    lat, lon = math.radians(obs.lat_deg), math.radians(obs.lon_deg)
    east = -math.sin(lon) * rx + math.cos(lon) * ry
    north = (
        -math.sin(lat) * math.cos(lon) * rx
        - math.sin(lat) * math.sin(lon) * ry
        + math.cos(lat) * rz
    )
    up = math.cos(lat) * math.cos(lon) * rx + math.cos(lat) * math.sin(lon) * ry + math.sin(lat) * rz
    range_km = math.sqrt(rx * rx + ry * ry + rz * rz)
    airless = math.degrees(math.atan2(up, math.hypot(east, north)))
    az = math.degrees(math.atan2(east, north)) % 360.0
    ra, dec = frame.j2000_from_horizon_vector(north, -east, up)

    # Cylindrical Earth-shadow approximation (TEME vs J2000 axes differ by <1 deg here).
    sx, sy, sz = sun_unit or sun_direction(frame)
    along = x * sx + y * sy + z * sz
    perpendicular = math.sqrt(max(0.0, x * x + y * y + z * z - along * along))
    sunlit = along > 0.0 or perpendicular > _EARTH_RADIUS_KM

    epoch_jd = satellite.jdsatepoch + satellite.jdsatepochF
    position_now = SatellitePosition(
        alt_deg=airless + ae.RefractionAngle(ae.Refraction.Normal, airless),
        airless_alt_deg=airless,
        az_deg=az,
        range_km=range_km,
        ra_j2000_deg=ra,
        dec_j2000_deg=dec,
        sunlit=sunlit,
        element_epoch=_J2000_UTC + timedelta(days=epoch_jd - _J2000_JD),
        element_age_days=(jd - satellite.jdsatepoch) + (fraction - satellite.jdsatepochF),
    )
    return position_now, None


def element_age_days(satellite: Satrec, at: datetime) -> float:
    """Days from the element-set epoch to ``at`` (negative before the epoch)."""
    jd, fraction = jday(at.year, at.month, at.day, at.hour, at.minute,
                        at.second + at.microsecond * 1e-6)
    return (jd - satellite.jdsatepoch) + (fraction - satellite.jdsatepochF)


@dataclass(frozen=True)
class TrackedObject:
    """A propagatable Space-Track object from the frozen materialization."""

    norad_cat_id: str
    object_id: str | None
    name: str | None
    aliases: tuple[str, ...]
    object_type: str | None
    identity_state: str | None
    decay_date: str | None
    satellite: Satrec


def tracked_objects(materialization: dict[str, Any]) -> tuple[list[TrackedObject], list[dict]]:
    """Split a ``space_objects`` materialization into propagatable objects and skips."""
    tracked: list[TrackedObject] = []
    skipped: list[dict] = []
    for item in materialization.get("objects", ()):
        norad = str(item.get("norad_cat_id") or "")
        gp_row = item.get("gp_row") or {}
        raw = gp_row.get("raw") if isinstance(gp_row, dict) else None
        if not raw:
            skipped.append({"norad_cat_id": norad, "reason": "no current GP elements"})
            continue
        ephemeris_type = str(raw.get("EPHEMERIS_TYPE") or "0").strip()
        if ephemeris_type not in ("0", "0.0"):
            skipped.append(
                {"norad_cat_id": norad, "reason": f"unsupported EPHEMERIS_TYPE {ephemeris_type}"}
            )
            continue
        satellite, problem = _build_satrec(raw)
        if satellite is None:
            skipped.append({"norad_cat_id": norad, "reason": problem or _MALFORMED_ROW})
            continue
        satcat = item.get("satcat_row") or {}
        name = gp_row.get("object_name") or satcat.get("object_name") or raw.get("OBJECT_NAME")
        object_type = gp_row.get("object_type") or raw.get("OBJECT_TYPE")
        decay = gp_row.get("decay_date") or satcat.get("decay")
        tracked.append(
            TrackedObject(
                norad_cat_id=norad,
                object_id=item.get("object_id") or gp_row.get("object_id"),
                name=str(name) if name else None,
                aliases=tuple(str(alias) for alias in item.get("aliases", ()) if alias),
                object_type=str(object_type) if object_type else None,
                identity_state=str(item["identity_state"]) if item.get("identity_state") else None,
                decay_date=str(decay) if decay else None,
                satellite=satellite,
            )
        )
    return tracked, skipped
