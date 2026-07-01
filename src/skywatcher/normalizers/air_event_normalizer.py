"""Normalize delayed or batch aircraft observations into Skywatcher air events."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping


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


def _iso(value: Any) -> str:
    raw = _text(value)
    if raw:
        return raw
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_air_event(record: Mapping[str, Any], source: str = "fr24_exports") -> dict[str, Any]:
    """Return a canonical, non-tactical air event record.

    The normalizer accepts common ADS-B/FR24-like field names while forcing
    delayed/batch semantics and guardrail metadata into every output record.
    """

    callsign = _text(record.get("callsign") or record.get("tail") or record.get("registration"))
    aircraft_id = _text(record.get("aircraft_id") or record.get("hex") or callsign)
    observed_at = _iso(record.get("observed_at") or record.get("timestamp") or record.get("event_timestamp"))
    lat = _float(record.get("lat") or record.get("latitude"))
    lon = _float(record.get("lon") or record.get("longitude"))
    fingerprint = "|".join([source, observed_at, aircraft_id, callsign, str(lat), str(lon)])

    return {
        "event_id": "air_" + sha1(fingerprint.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "source_tier": "T1" if source == "adsb_exchange" else "T2",
        "mode": "delayed_or_rate_limited" if source == "adsb_exchange" else "batch_file",
        "observed_at": observed_at,
        "lat": lat,
        "lon": lon,
        "aircraft_id": aircraft_id,
        "callsign": callsign,
        "altitude_ft": _float(record.get("altitude_ft") or record.get("alt_baro") or record.get("altitude")),
        "speed_kt": _float(record.get("speed_kt") or record.get("gs") or record.get("groundspeed")),
        "heading_deg": _float(record.get("heading_deg") or record.get("track") or record.get("heading")),
        "event_type": _text(record.get("event_type"), "air_observation"),
        "confidence": max(0.0, min(1.0, _float(record.get("confidence"), 0.75))),
        "tactical_public_tracking": False,
    }
