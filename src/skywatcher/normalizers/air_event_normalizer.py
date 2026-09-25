"""Normalize delayed or batch aircraft observations into Skywatcher air events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
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
    lat = _float(record.get("lat") or record.get("latitude"))
    lon = _float(record.get("lon") or record.get("longitude"))
    fingerprint = "|".join(
        [
            source,
            observed_at,
            aircraft_id,
            source_callsign,
            source_registration,
            source_icao24,
            str(lat),
            str(lon),
        ]
    )
    identity_present = any(
        (source_callsign, source_registration, source_icao24, source_aircraft_type, aircraft_id)
    )

    return {
        "event_id": "air_" + sha1(fingerprint.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "source_tier": "T1" if source == "adsb_exchange" else "T2",
        "mode": "delayed_or_rate_limited" if source == "adsb_exchange" else "batch_file",
        "observed_at": observed_at,
        "lat": lat,
        "lon": lon,
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
