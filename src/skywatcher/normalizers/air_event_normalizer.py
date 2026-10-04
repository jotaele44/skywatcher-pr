"""Normalize delayed or batch aircraft observations into Skywatcher air events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    """Parse a non-spatial numeric value with a caller-selected fallback."""
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _first_text(record: Mapping[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = _text(record.get(name))
        if value:
            return value
    return ""


def _first_coordinate_value(
    record: Mapping[str, Any],
    primary: str,
    fallback: str,
) -> tuple[str | None, Any]:
    """Choose one source coordinate field without treating numeric zero as missing.

    A present, non-blank primary value is authoritative for parsing even when it
    is invalid; an invalid primary value must not silently fall through to the
    fallback field. Blank/missing primary values may use the fallback.
    """
    if primary in record and record.get(primary) not in (None, ""):
        return primary, record.get(primary)
    if fallback in record and record.get(fallback) not in (None, ""):
        return fallback, record.get(fallback)
    if primary in record:
        return primary, record.get(primary)
    if fallback in record:
        return fallback, record.get(fallback)
    return None, None


def _coordinate(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> tuple[float | None, str]:
    """Parse a coordinate fail-closed.

    Missing and invalid coordinates remain non-spatial. In particular they never
    default to 0.0, because (0, 0) is a real location rather than a null sentinel.
    """
    if value in (None, ""):
        return None, "MISSING"
    if isinstance(value, bool):
        return None, "INVALID"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, "INVALID"
    if not minimum <= number <= maximum:
        return None, "INVALID"
    return number, "VALID"


def _iso(value: Any) -> str:
    raw = _text(value)
    if raw:
        return raw
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_air_event(record: Mapping[str, Any], source: str = "fr24_exports") -> dict[str, Any]:
    """Return a canonical, non-tactical air event record.

    The normalizer accepts common ADS-B/FR24-like field names while forcing
    delayed/batch semantics and guardrail metadata into every output record.

    Source-native identity dimensions are preserved independently. A blank
    callsign may fall back to registration for the legacy display field, but
    the source_identity block records that the callsign itself was unobserved.

    Coordinate handling is deliberately stricter than other numeric fields:
    missing/invalid latitude or longitude produces nullable geometry plus an
    explicit geometry status; it never fabricates the geographic point (0, 0).
    Raw source coordinate values are preserved separately.
    """

    source_callsign = _first_text(record, ("callsign", "call_sign"))
    source_registration = _first_text(
        record,
        ("registration", "reg", "tail", "tail_number", "source_registration"),
    )
    source_icao24 = _first_text(
        record,
        ("icao24", "hex", "hex_code", "mode_s", "transponder"),
    )
    source_aircraft_type = _first_text(
        record,
        ("aircraft_type", "aircraftType", "type_code", "typecode"),
    )

    callsign = source_callsign or source_registration
    aircraft_id = (
        _first_text(record, ("aircraft_id", "aircraft_identity"))
        or source_icao24
        or source_registration
        or source_callsign
    )
    observed_at = _iso(
        record.get("observed_at") or record.get("timestamp") or record.get("event_timestamp")
    )

    lat_field, lat_raw = _first_coordinate_value(record, "lat", "latitude")
    lon_field, lon_raw = _first_coordinate_value(record, "lon", "longitude")
    lat, lat_status = _coordinate(lat_raw, minimum=-90.0, maximum=90.0)
    lon, lon_status = _coordinate(lon_raw, minimum=-180.0, maximum=180.0)
    if lat_status == "VALID" and lon_status == "VALID":
        geometry_status = "LOCATED"
    elif "INVALID" in {lat_status, lon_status}:
        geometry_status = "INVALID"
    else:
        geometry_status = "UNRESOLVED"

    # Preserve historical deterministic IDs for valid coordinates. Unknown or
    # invalid coordinates include their raw/state material so distinct source
    # manifestations are not collapsed merely because both parse to None.
    fingerprint_lat = str(lat) if lat is not None else f"{lat_status}:{lat_raw!r}"
    fingerprint_lon = str(lon) if lon is not None else f"{lon_status}:{lon_raw!r}"
    fingerprint = "|".join(
        [
            source,
            observed_at,
            aircraft_id,
            source_callsign,
            source_registration,
            source_icao24,
            fingerprint_lat,
            fingerprint_lon,
        ]
    )
    identity_present = any(
        (source_callsign, source_registration, source_icao24, source_aircraft_type, aircraft_id)
    )

    return {
        "schema_version": "2.0",
        "event_id": "air_" + sha1(fingerprint.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "source_tier": "T1" if source == "adsb_exchange" else "T2",
        "mode": "delayed_or_rate_limited" if source == "adsb_exchange" else "batch_file",
        "observed_at": observed_at,
        "lat": lat,
        "lon": lon,
        "geometry_status": geometry_status,
        "coordinate_status": {
            "lat": lat_status,
            "lon": lon_status,
        },
        "source_coordinates": {
            "selected_lat_field": lat_field,
            "selected_lon_field": lon_field,
            "lat_raw": record.get("lat") if "lat" in record else None,
            "latitude_raw": record.get("latitude") if "latitude" in record else None,
            "lon_raw": record.get("lon") if "lon" in record else None,
            "longitude_raw": record.get("longitude") if "longitude" in record else None,
        },
        "aircraft_id": aircraft_id,
        "registration": source_registration or None,
        "callsign": callsign,
        "icao24": source_icao24 or None,
        "aircraft_type": source_aircraft_type or None,
        "source_identity": {
            "callsign": source_callsign or None,
            "registration": source_registration or None,
            "icao24": source_icao24 or None,
            "aircraft_type": source_aircraft_type or None,
        },
        "identity_state": "SOURCE_IDENTITY_PRESENT" if identity_present else "UNRESOLVED",
        "altitude_ft": _float(
            record.get("altitude_ft") or record.get("alt_baro") or record.get("altitude")
        ),
        "speed_kt": _float(record.get("speed_kt") or record.get("gs") or record.get("groundspeed")),
        "heading_deg": _float(record.get("heading_deg") or record.get("track") or record.get("heading")),
        "event_type": _text(record.get("event_type"), "air_observation"),
        "confidence": max(0.0, min(1.0, _float(record.get("confidence"), 0.75))),
        "tactical_public_tracking": False,
    }
