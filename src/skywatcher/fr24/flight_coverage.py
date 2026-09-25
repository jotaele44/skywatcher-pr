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


def _datetime_from_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _date_from_iso(value: Any) -> date | None:
    parsed = _datetime_from_iso(value)
    return parsed.date() if parsed is not None else None


def _source_folders(record: dict[str, Any]) -> list[str]:
    folders: list[str] = []
    for item in record.get("sourceManifestations") or []:
        if not isinstance(item, dict):
            continue
        folder = str(item.get("folderRaw") or "").strip().upper()
        if folder not in folders:
            folders.append(folder)
    return folders


def _meaningful_folders(record: dict[str, Any]) -> list[str]:
    return [
        folder for folder in _source_folders(record)
        if folder.lower() not in _GENERIC_FOLDERS
    ]


def _identity(record: dict[str, Any]) -> tuple[str, str]:
    callsign = str(record.get("callsignRaw") or "").strip().upper()
    if callsign:
        return callsign, "callsign_raw"

    folders = _meaningful_folders(record)
    if len(folders) == 1:
        return folders[0], "single_source_folder_provisional"
    return UNRESOLVED_IDENTITY, "unresolved"


def _verification_reason(record: dict[str, Any]) -> str | None:
    if not (isinstance(record.get("pointCount"), int) and record.get("pointCount", 0) > 0):
        return None
    callsign = str(record.get("callsignRaw") or "").strip().upper()
    folders = _meaningful_folders(record)
    if not callsign:
        return "IDCONF" if len(folders) > 1 else "BLANK"
    if any(folder != callsign for folder in folders):
        return "MISFILED"
    return None


def _has_kml(record: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and bool(item.get("kmlPresent"))
        for item in (record.get("sourceManifestations") or [])
    )


def _window(from_day: date, to_day: date, horizon: date) -> dict[str, Any]:
    recoverable_from = max(from_day, horizon)
    expired = to_day < recoverable_from
    recoverable_days = 0 if expired else (to_day - recoverable_from).days + 1
    lost_to = min(to_day, date.fromordinal(horizon.toordinal() - 1))
    lost_days = max(0, (lost_to - from_day).days + 1)
    return {
        "recoverable_from": None if expired else recoverable_from.isoformat(),
        "recoverable_to": None if expired else to_day.isoformat(),
        "recoverable_days": recoverable_days,
        "lost_days": lost_days,
        "state": "BEYOND_LOOKBACK" if expired else ("PARTLY_RECOVERABLE" if lost_days else "RECOVERABLE"),
    }


def _flight_id_time_model(records: list[dict[str, Any]]) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for record in records:
        if not (isinstance(record.get("pointCount"), int) and record.get("pointCount", 0) > 0):
            continue
        source_id = record.get("sourceFlightIdRaw")
        observed = _datetime_from_iso(record.get("startTimeUtc"))
        if not isinstance(source_id, str) or observed is None:
            continue
        try:
            fid = int(source_id, 16)
        except ValueError:
            continue
        points.append((fid, observed.timestamp()))
    return sorted(set(points))


def _estimate_flight_id_day(
    model: list[tuple[int, float]],
    source_id: Any,
) -> tuple[date | None, bool]:
    if not isinstance(source_id, str) or len(model) < 2:
        return None, False
    try:
        target = int(source_id, 16)
    except ValueError:
        return None, False
    if target <= model[0][0]:
        return datetime.fromtimestamp(model[0][1], timezone.utc).date(), True
    if target >= model[-1][0]:
        return datetime.fromtimestamp(model[-1][1], timezone.utc).date(), True

    lo = 0
    hi = len(model) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if model[mid][0] <= target:
            lo = mid
        else:
            hi = mid
    a_id, a_ts = model[lo]
    b_id, b_ts = model[hi]
    estimate = a_ts + (b_ts - a_ts) * (target - a_id) / (b_id - a_id or 1)
    return datetime.fromtimestamp(estimate, timezone.utc).date(), False


def _prioritize(
    item: dict[str, Any],
    *,
    as_of: date,
    lookback_days: int,
    base: int,
    watch: bool = False,
    bonus: int = 0,
    no_urgency: bool = False,
) -> dict[str, Any]:
    recoverable_from = item.get("recoverable_from")
    expired = item.get("state") == "BEYOND_LOOKBACK"
    deadline: date | None = None
    days_left: int | None = None
    if recoverable_from and not expired:
        deadline = date.fromordinal(date.fromisoformat(recoverable_from).toordinal() + lookback_days)
        days_left = (deadline - as_of).days

    score = base + (20 if watch else 0)
    if days_left is not None and not no_urgency:
        score += 30 if days_left <= 7 else 20 if days_left <= 30 else 10 if days_left <= 60 else 0
    score += bonus
    item["priority_score"] = int(round(score))
    item["priority_tier"] = (
        "X" if expired else "P1" if score >= 90 else "P2" if score >= 60 else "P3"
    )
    item["deadline"] = deadline.isoformat() if deadline is not None else None
    item["days_left"] = days_left
    return item


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
    fid_model = _flight_id_time_model(records)
    for record in records:
        if not isinstance(record, dict):
            continue
        ident, basis = _identity(record)
        groups[ident].append(record)
        basis_by_identity[ident].add(basis)
    for watched in watch:
        groups.setdefault(watched, [])

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
        if not rows and ident in watch:
            identity_state = "WATCHLIST_ONLY"
        elif basis_set == {"callsign_raw"}:
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
                queue.append(_prioritize(
                    gap,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    base=40,
                    watch=ident in watch,
                    bonus=min(30, round((length / cadence) * 3)),
                ))

        if observed_days and (ident in watch or len(counted) >= 3):
            since = (as_of - observed_days[-1]).days
            if since >= stale_days:
                from_day = date.fromordinal(observed_days[-1].toordinal() + 1)
                recovery = _window(from_day, as_of, horizon)
                active = since <= dormant_days
                queue.append(_prioritize({
                    "type": "STALE",
                    "identity": ident,
                    "from": from_day.isoformat(),
                    "to": as_of.isoformat(),
                    "days": since,
                    "activity_state": "ACTIVE_RECENTLY" if active else "DORMANT",
                    **recovery,
                    "evidence_note": "Trailing archive absence; confirm operating status before treating as an acquisition priority.",
                }, as_of=as_of, lookback_days=lookback_days,
                    base=45 if active else 20,
                    watch=ident in watch,
                    bonus=min(20, since // 10) if active else 0,
                    no_urgency=not active,
                ))

        if not rows and ident in watch:
            recovery = _window(horizon, as_of, horizon)
            queue.append(_prioritize({
                "type": "WATCH",
                "identity": ident,
                "from": horizon.isoformat(),
                "to": as_of.isoformat(),
                **recovery,
                "evidence_note": "Watchlist identity has no corpus records; fetch the current look-back window without treating archive absence as negative evidence.",
            }, as_of=as_of, lookback_days=lookback_days, base=50, watch=True))

        empty_rows = [
            row for row in rows
            if isinstance(row.get("pointCount"), int) and row.get("pointCount") == 0
        ]
        for row in empty_rows:
            estimated_day, edge = _estimate_flight_id_day(fid_model, row.get("sourceFlightIdRaw"))
            if estimated_day is not None:
                recovery = _window(estimated_day, estimated_day, horizon)
                item = {
                    "type": "EMPTY",
                    "identity": ident,
                    "source_flight_id_raw": row.get("sourceFlightIdRaw"),
                    "estimated_day": estimated_day.isoformat(),
                    "estimate_edge": edge,
                    "from": estimated_day.isoformat(),
                    "to": estimated_day.isoformat(),
                    **recovery,
                    "evidence_note": "Header-only CSV; estimated date is interpolated from FR24 flight-ID order and is not a recorded trajectory timestamp.",
                }
            else:
                item = {
                    "type": "EMPTY",
                    "identity": ident,
                    "source_flight_id_raw": row.get("sourceFlightIdRaw"),
                    "estimated_day": None,
                    "estimate_edge": False,
                    "state": "DATE_UNRESOLVED",
                    "recoverable_from": None,
                    "recoverable_to": None,
                    "recoverable_days": 0,
                    "lost_days": 0,
                    "evidence_note": "Header-only CSV with no bounded date estimate; no trajectory absence inference is allowed.",
                }
            queue.append(_prioritize(
                item, as_of=as_of, lookback_days=lookback_days, base=40, watch=ident in watch
            ))

        if missing_kml:
            queue.append(_prioritize({
                "type": "KML",
                "identity": ident,
                "record_count": missing_kml,
                "state": "REGENERABLE_OR_REFETCH",
                "evidence_note": "CSV-backed records lack reported KML presence; this is not missing-flight evidence.",
            }, as_of=as_of, lookback_days=lookback_days, base=10, watch=ident in watch))

        verification_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            reason = _verification_reason(row)
            if reason:
                verification_groups[reason].append(row)
        for reason, verification_rows in sorted(verification_groups.items()):
            source_ids = [
                row.get("sourceFlightIdRaw")
                for row in verification_rows
                if row.get("sourceFlightIdRaw")
            ]
            queue.append(_prioritize({
                "type": "VERIFY",
                "identity": ident,
                "record_count": len(verification_rows),
                "state": reason,
                "source_flight_ids": source_ids,
                "evidence_note": (
                    "Blank callsign requires source-identity review; folder evidence is provisional."
                    if reason == "BLANK"
                    else "Blank callsign appears under multiple non-generic folders; no folder is promoted to identity."
                    if reason == "IDCONF"
                    else "Callsigned record appears under a different non-generic source folder; callsign remains source evidence, not a canonical identity promotion."
                ),
            }, as_of=as_of, lookback_days=lookback_days, base=25, watch=ident in watch))

        identities.append(item)

    state_order = {"RECOVERABLE": 0, "PARTLY_RECOVERABLE": 1, "BEYOND_LOOKBACK": 2}
    queue.sort(key=lambda item: (
        {"P1": 0, "P2": 1, "P3": 2, "X": 3}.get(item.get("priority_tier"), 9),
        -int(item.get("priority_score") or 0),
        {"WATCH": 0, "EMPTY": 1, "VERIFY": 2, "GAP": 3, "STALE": 4, "KML": 5}.get(item["type"], 9),
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
            "provisional_or_unresolved_identity_count": sum(
                1 for item in identities
                if item["identity_state"] not in {"SOURCE_CALLSIGN", "WATCHLIST_ONLY"}
            ),
            "watchlist_only_identity_count": sum(1 for item in identities if item["identity_state"] == "WATCHLIST_ONLY"),
            "counted_flight_count": sum(item["counted_flight_count"] for item in identities),
            "observed_day_count_sum": sum(item["observed_day_count"] for item in identities),
            "gap_count": len(gaps),
            "recoverable_gap_count": sum(1 for item in gaps if item["state"] == "RECOVERABLE"),
            "partial_gap_count": sum(1 for item in gaps if item["state"] == "PARTLY_RECOVERABLE"),
            "beyond_lookback_gap_count": sum(1 for item in gaps if item["state"] == "BEYOND_LOOKBACK"),
            "queue_count": len(queue),
            "verification_count": sum(1 for item in queue if item["type"] == "VERIFY"),
            "queue_type_counts": {
                queue_type: sum(1 for item in queue if item["type"] == queue_type)
                for queue_type in ("GAP", "STALE", "WATCH", "EMPTY", "KML", "VERIFY")
            },
            "priority_tier_counts": {
                tier: sum(1 for item in queue if item.get("priority_tier") == tier)
                for tier in ("P1", "P2", "P3", "X")
            },
            "missing_kml_record_count": sum(item["kml_missing_count"] for item in identities),
        },
        "identities": identities,
        "gaps": gaps,
        "acquisition_queue": queue,
    }
