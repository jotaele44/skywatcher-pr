"""Coverage and acquisition ledger for persisted flight-corpus snapshots.

This module is corpus/coverage logic only. It does not infer mission semantics,
targeting, anomaly status, or analytical flight identity.

Defaults intentionally mirror the Master Flight Log v1 producer:
- 365-day look-back horizon
- internal gap >=14 days
- internal gap >=4x median observed flight-day cadence
- stale after 7 days
- dormant after 60 days
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_GAP_MIN_DAYS = 14
DEFAULT_GAP_MULTIPLIER = 4.0
DEFAULT_STALE_DAYS = 7
DEFAULT_DORMANT_DAYS = 60
DEFAULT_WATCHLIST = ("N5854Z", "N767PD", "C6062", "N684JB")

UNRESOLVED_IDENTITY = "UNRESOLVED_SOURCE_CALLSIGN"
_GENERIC_FOLDERS = {"", "csv", "empty"}


def _date_from_iso(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except ValueError:
        return None


def _identity(record: dict[str, Any]) -> tuple[str, str]:
    callsign = str(record.get("callsignRaw") or "").strip().upper()
    if callsign:
        return callsign, "callsign_raw"

    folders = {
        str(item.get("folderRaw") or "").strip().upper()
        for item in (record.get("sourceManifestations") or [])
        if isinstance(item, dict)
    }
    folders = {folder for folder in folders if folder.lower() not in _GENERIC_FOLDERS}
    if len(folders) == 1:
        return next(iter(folders)), "single_source_folder_provisional"
    return UNRESOLVED_IDENTITY, "unresolved"


def _has_kml(record: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and bool(item.get("kmlPresent"))
        for item in (record.get("sourceManifestations") or [])
    )


def _window(from_day: date, to_day: date, horizon: date) -> dict[str, Any]:
    recoverable_from = max(from_day, horizon)
    expired = to_day < recoverable_from
    recoverable_days = 0 if expired else (to_day - recoverable_from).days + 1
    lost_to = min(to_day, horizon.fromordinal(horizon.toordinal() - 1))
    lost_days = max(0, (lost_to - from_day).days + 1)
    return {
        "recoverable_from": None if expired else recoverable_from.isoformat(),
        "recoverable_to": None if expired else to_day.isoformat(),
        "recoverable_days": recoverable_days,
        "lost_days": lost_days,
        "state": "BEYOND_LOOKBACK" if expired else ("PARTLY_RECOVERABLE" if lost_days else "RECOVERABLE"),
    }


def _superseded_record_ids(records: list[dict[str, Any]]) -> set[int]:
    """Mirror the MFL overlap rule: overlapping pair >60s, one source id missing."""
    indexed: list[tuple[int, datetime, datetime, bool]] = []
    for idx, record in enumerate(records):
        start = record.get("startTimeUtc")
        end = record.get("endTimeUtc")
        if not start or not end:
            continue
        try:
            t0 = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        except ValueError:
            continue
        indexed.append((idx, t0, t1, bool(record.get("sourceFlightIdRaw"))))

    indexed.sort(key=lambda item: item[1])
    superseded: set[int] = set()
    for i, a in enumerate(indexed):
        for b in indexed[i + 1 :]:
            if b[1] >= a[2]:
                break
            overlap = (min(a[2], b[2]) - b[1]).total_seconds()
            if overlap <= 60 or a[3] == b[3]:
                continue
            superseded.add(a[0] if not a[3] else b[0])
    return superseded


def build_coverage_ledger(
    records: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    gap_min_days: int = DEFAULT_GAP_MIN_DAYS,
    gap_multiplier: float = DEFAULT_GAP_MULTIPLIER,
    stale_days: int = DEFAULT_STALE_DAYS,
    dormant_days: int = DEFAULT_DORMANT_DAYS,
    watchlist: tuple[str, ...] = DEFAULT_WATCHLIST,
) -> dict[str, Any]:
    """Build source-identity coverage + acquisition queues from normalized records."""
    as_of = as_of or datetime.now(timezone.utc).date()
    horizon = date.fromordinal(as_of.toordinal() - lookback_days)
    watch = {item.upper() for item in watchlist}

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    basis_by_identity: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if not isinstance(record, dict):
            continue
        ident, basis = _identity(record)
        groups[ident].append(record)
        basis_by_identity[ident].add(basis)

    identities: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []

    for ident in sorted(groups):
        rows = groups[ident]
        superseded = _superseded_record_ids(rows)
        counted = [
            row
            for idx, row in enumerate(rows)
            if idx not in superseded
            and isinstance(row.get("pointCount"), int)
            and row.get("pointCount", 0) > 0
            and _date_from_iso(row.get("startTimeUtc")) is not None
        ]
        observed_days = sorted({_date_from_iso(row.get("startTimeUtc")) for row in counted})
        observed_days = [item for item in observed_days if item is not None]
        intervals = [
            (observed_days[i] - observed_days[i - 1]).days
            for i in range(1, len(observed_days))
        ]
        cadence = max(1.0, float(median(intervals))) if intervals else None
        kml_count = sum(1 for row in counted if _has_kml(row))
        missing_kml = len(counted) - kml_count

        basis_set = basis_by_identity[ident]
        if basis_set == {"callsign_raw"}:
            identity_state = "SOURCE_CALLSIGN"
        elif "callsign_raw" in basis_set:
            identity_state = "MIXED_SOURCE_IDENTITY"
        elif "single_source_folder_provisional" in basis_set:
            identity_state = "PROVISIONAL_FOLDER_IDENTITY"
        else:
            identity_state = "UNRESOLVED"

        item = {
            "identity": ident,
            "identity_state": identity_state,
            "record_count": len(rows),
            "counted_flight_count": len(counted),
            "superseded_count": len(superseded),
            "observed_day_count": len(observed_days),
            "first_observed_day": observed_days[0].isoformat() if observed_days else None,
            "last_observed_day": observed_days[-1].isoformat() if observed_days else None,
            "median_cadence_days": cadence,
            "kml_present_count": kml_count,
            "kml_missing_count": missing_kml,
            "watchlist": ident in watch,
        }

        if len(observed_days) >= 2 and cadence is not None:
            for idx in range(1, len(observed_days)):
                previous = observed_days[idx - 1]
                current = observed_days[idx]
                length = (current - previous).days - 1
                if length < gap_min_days or length < gap_multiplier * cadence:
                    continue
                from_day = date.fromordinal(previous.toordinal() + 1)
                to_day = date.fromordinal(current.toordinal() - 1)
                recovery = _window(from_day, to_day, horizon)
                gap = {
                    "type": "GAP",
                    "identity": ident,
                    "from": from_day.isoformat(),
                    "to": to_day.isoformat(),
                    "days": length,
                    "median_cadence_days": cadence,
                    "cadence_multiple": round(length / cadence, 3),
                    **recovery,
                    "evidence_note": "Unobserved interval between recorded flight-days; absence is not negative flight evidence.",
                }
                gaps.append(gap)
                queue.append(gap)

        if observed_days and (ident in watch or len(counted) >= 3):
            since = (as_of - observed_days[-1]).days
            if since >= stale_days:
                from_day = date.fromordinal(observed_days[-1].toordinal() + 1)
                recovery = _window(from_day, as_of, horizon)
                queue.append({
                    "type": "STALE",
                    "identity": ident,
                    "from": from_day.isoformat(),
                    "to": as_of.isoformat(),
                    "days": since,
                    "activity_state": "ACTIVE_RECENTLY" if since <= dormant_days else "DORMANT",
                    **recovery,
                    "evidence_note": "Trailing archive absence; confirm operating status before treating as an acquisition priority.",
                })

        if missing_kml:
            queue.append({
                "type": "KML",
                "identity": ident,
                "record_count": missing_kml,
                "state": "REGENERABLE_OR_REFETCH",
                "evidence_note": "CSV-backed records lack reported KML presence; this is not missing-flight evidence.",
            })

        if identity_state != "SOURCE_CALLSIGN":
            queue.append({
                "type": "VERIFY",
                "identity": ident,
                "record_count": len(rows),
                "state": identity_state,
                "evidence_note": "Identity is provisional or unresolved; no registration promotion is allowed from folder proximity alone.",
            })

        identities.append(item)

    state_order = {"RECOVERABLE": 0, "PARTLY_RECOVERABLE": 1, "BEYOND_LOOKBACK": 2}
    queue.sort(key=lambda item: (
        {"VERIFY": 0, "GAP": 1, "STALE": 2, "KML": 3}.get(item["type"], 9),
        state_order.get(item.get("state"), 9),
        item["identity"],
        item.get("from") or "",
    ))

    return {
        "parameters": {
            "as_of": as_of.isoformat(),
            "lookback_days": lookback_days,
            "horizon": horizon.isoformat(),
            "gap_min_days": gap_min_days,
            "gap_multiplier": gap_multiplier,
            "stale_days": stale_days,
            "dormant_days": dormant_days,
            "watchlist": list(watchlist),
        },
        "summary": {
            "input_records": len(records),
            "identity_count": len(identities),
            "source_callsign_identity_count": sum(1 for item in identities if item["identity_state"] == "SOURCE_CALLSIGN"),
            "provisional_or_unresolved_identity_count": sum(1 for item in identities if item["identity_state"] != "SOURCE_CALLSIGN"),
            "counted_flight_count": sum(item["counted_flight_count"] for item in identities),
            "observed_day_count_sum": sum(item["observed_day_count"] for item in identities),
            "gap_count": len(gaps),
            "recoverable_gap_count": sum(1 for item in gaps if item["state"] == "RECOVERABLE"),
            "partial_gap_count": sum(1 for item in gaps if item["state"] == "PARTLY_RECOVERABLE"),
            "beyond_lookback_gap_count": sum(1 for item in gaps if item["state"] == "BEYOND_LOOKBACK"),
            "queue_count": len(queue),
            "missing_kml_record_count": sum(item["kml_missing_count"] for item in identities),
        },
        "identities": identities,
        "gaps": gaps,
        "acquisition_queue": queue,
    }
