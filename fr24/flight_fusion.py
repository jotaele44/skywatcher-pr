"""Same-flight screenshot fusion (strategy #3).

Temporal-wave grouping clusters same-aircraft observations; this module fuses a
wave into one multi-point record. Endpoint distance candidates may accompany the
fused record, but discovery-only matches cannot silently become route truth.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from fr24.ocr_analysis_vector import _aircraft_identity, _parse_playback_dt

FUSION_VERSION = "fr24_flight_fusion_v0.1.0"


def aircraft_identity(row: dict) -> str:
    return _aircraft_identity(row)


def _row_iso(row: dict) -> str:
    for key in ("vector_playback_iso", "timestamp", "timestamp_iso"):
        value = (row.get(key) or "").strip() if isinstance(row.get(key), str) else ""
        if value:
            return value
    parsed = _parse_playback_dt(row)
    return parsed.isoformat() if parsed else ""


def _float_or_none(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _consensus(rows: list[dict], key: str) -> str:
    counts = Counter(
        str(row.get(key)).strip()
        for row in rows
        if row.get(key) is not None and str(row.get(key)).strip()
    )
    return counts.most_common(1)[0][0] if counts else ""


def _duration_minutes(first_iso: str, last_iso: str) -> float:
    if not first_iso or not last_iso or first_iso == last_iso:
        return 0.0
    try:
        t0 = datetime.fromisoformat(first_iso)
        t1 = datetime.fromisoformat(last_iso)
        return round((t1 - t0).total_seconds() / 60.0, 2)
    except ValueError:
        return 0.0


def fuse_wave(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("fuse_wave requires at least one row")

    def sort_key(row: dict):
        iso = _row_iso(row)
        return (0 if iso else 1, iso, row.get("image_name") or "")

    ordered = sorted(rows, key=sort_key)
    identity = aircraft_identity(ordered[0])
    isos = [iso for iso in (_row_iso(r) for r in ordered) if iso]
    first_iso = isos[0] if isos else ""
    last_iso = isos[-1] if isos else ""

    points = []
    for row in ordered:
        points.append(
            {
                "image_name": (row.get("image_name") or "").strip(),
                "timestamp_iso": _row_iso(row),
                "lat": _float_or_none(
                    row.get("lat") if row.get("lat") is not None else row.get("latitude")
                ),
                "lon": _float_or_none(
                    row.get("lon") if row.get("lon") is not None else row.get("longitude")
                ),
                "altitude_ft": _int_or_none(
                    row.get("barometric_altitude_ft") or row.get("altitude_ft")
                ),
            }
        )

    confidences = [
        c
        for c in (
            _float_or_none(
                row.get("confidence")
                if row.get("confidence") is not None
                else row.get("vector_max_confidence")
            )
            for row in ordered
        )
        if c is not None
    ]
    blended = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

    altitudes = [p["altitude_ft"] for p in points if p["altitude_ft"] is not None]
    speeds = [
        s
        for s in (_float_or_none(r.get("ground_speed_mph")) for r in ordered)
        if s is not None
    ]

    return {
        "aircraft_identity": identity,
        "registration": _consensus(ordered, "registration"),
        "callsign": _consensus(ordered, "callsign_or_label")
        or _consensus(ordered, "callsign"),
        "aircraft_type": _consensus(ordered, "aircraft_type"),
        "operator": _consensus(ordered, "operator"),
        "origin_code": _consensus(ordered, "origin_code"),
        "destination_code": _consensus(ordered, "destination_code"),
        "num_screenshots": len(ordered),
        "first_seen_iso": first_iso,
        "last_seen_iso": last_iso,
        "duration_minutes": _duration_minutes(first_iso, last_iso),
        "points": points,
        "max_altitude_ft": max(altitudes) if altitudes else None,
        "avg_speed_mph": round(sum(speeds) / len(speeds), 2) if speeds else None,
        "confidence": blended,
        "confirmation_status": "not_confirmed",
        "fusion_version": FUSION_VERSION,
    }


def fuse_rows(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[aircraft_identity(row)].append(row)
    return [fuse_wave(group) for _, group in sorted(groups.items())]


def endpoint_event_can_promote_route(event: dict) -> bool:
    """Require explicit reviewed identity before endpoint data can alter a route.

    Distance, nearest-neighbour, screenshot label, or any event still marked
    CANDIDATE_NOT_IDENTITY is never sufficient regardless of confidence.
    """
    return (
        event.get("review_status") == "promoted"
        and event.get("identity_state") == "CERTIFIED"
        and event.get("association_state") != "DISCOVERY_ONLY"
    )


def to_adapter_row(
    fused: dict,
    *,
    candidate_id: str = "",
    selection_status: str = "",
    endpoint_events: list[dict] | None = None,
) -> dict:
    """Shape a fused record for the Spiderweb adapter without heuristic promotion.

    OCR/source-declared origin/destination remain intact. Endpoint candidates can
    replace them only after explicit promotion plus certified facility identity.
    """
    origin = fused.get("origin_code") or ""
    destination = fused.get("destination_code") or ""
    for event in endpoint_events or []:
        if not endpoint_event_can_promote_route(event):
            continue
        code = event.get("matched_facility_code") or event.get("matched_facility_id") or ""
        if event.get("endpoint_type") == "start" and code:
            origin = code
        elif event.get("endpoint_type") == "end" and code:
            destination = code

    first_iso = fused.get("first_seen_iso") or ""
    playback_date, playback_time = "", ""
    if "T" in first_iso:
        playback_date, time_part = first_iso.split("T", 1)
        playback_time = time_part[:5]
    elif first_iso:
        playback_date = first_iso

    identity = fused.get("aircraft_identity") or ""
    return {
        "candidate_id": candidate_id
        or f"fr24-fused::{identity}::{playback_date or 'undated'}",
        "callsign_or_label": fused.get("callsign")
        or fused.get("registration")
        or identity,
        "registration": fused.get("registration") or "",
        "aircraft_type": fused.get("aircraft_type") or "",
        "operator": fused.get("operator") or "",
        "origin_code": origin,
        "destination_code": destination,
        "barometric_altitude_ft": fused.get("max_altitude_ft") or "",
        "ground_speed_mph": fused.get("avg_speed_mph") or "",
        "playback_date": playback_date,
        "playback_time": playback_time,
        "num_screenshots": fused.get("num_screenshots") or 1,
        "selection_status": selection_status,
        "confirmation_status": "not_confirmed",
        "fusion_version": FUSION_VERSION,
    }
