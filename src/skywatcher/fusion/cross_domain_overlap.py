"""Historical/batch cross-domain overlap scoring for aggregate review."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha1
from typing import Mapping, Sequence

from skywatcher.fusion.coastal_corridor_index import haversine_km


def _parse_time(value: object) -> datetime:
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _record_id(record: Mapping[str, object]) -> str:
    return str(record.get("record_id") or record.get("event_id") or "unknown")


def find_cross_domain_overlaps(
    air_events: Sequence[Mapping[str, object]],
    context_records: Sequence[Mapping[str, object]],
    *,
    max_minutes: float = 60.0,
    max_distance_km: float = 25.0,
    min_confidence: float = 0.40,
) -> list[dict[str, object]]:
    """Find aggregate overlaps between air events and historical coastal context.

    This emits analytical review candidates only. Any context record marked as
    operational-use-allowed is ignored.
    """

    overlaps: list[dict[str, object]] = []
    for air in air_events:
        if air.get("tactical_public_tracking") is not False:
            continue
        air_time = _parse_time(air["observed_at"])
        for ctx in context_records:
            if ctx.get("operational_use_allowed") is not False:
                continue
            ctx_time = _parse_time(ctx["observed_at"])
            minutes = abs((air_time - ctx_time).total_seconds()) / 60.0
            if minutes > max_minutes:
                continue
            distance = haversine_km(float(air["lat"]), float(air["lon"]), float(ctx["lat"]), float(ctx["lon"]))
            if distance > max_distance_km:
                continue
            corridor_match = air.get("corridor_id") and air.get("corridor_id") == ctx.get("corridor_id")
            confidence = 0.45 + (0.25 if corridor_match else 0.0) + (0.15 * (1 - minutes / max_minutes)) + (0.15 * (1 - distance / max_distance_km))
            confidence = round(max(0.0, min(1.0, confidence)), 3)
            if confidence < min_confidence:
                continue
            seed = "|".join([_record_id(air), _record_id(ctx), str(minutes), str(distance)])
            overlaps.append({
                "overlap_id": "overlap_" + sha1(seed.encode("utf-8")).hexdigest()[:16],
                "air_event_ids": [_record_id(air)],
                "maritime_record_ids": [_record_id(ctx)],
                "corridor_id": air.get("corridor_id") or ctx.get("corridor_id"),
                "time_window_minutes": round(minutes, 3),
                "distance_km": round(distance, 3),
                "confidence": confidence,
                "explanation": "Aggregate historical/batch spatial-temporal overlap; not an operational cue.",
            })
    return overlaps
