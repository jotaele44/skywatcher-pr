#!/usr/bin/env python3
"""
FR24 DAILY HARVEST BATCH BUILDER  (auto-updating status)

Generates ``data/todays_batch.csv`` — the prioritized list of flights to export
from FlightRadar24 Gold today, given the daily 25-export quota.

WHY THIS EXISTS / THE BUG IT FIXES
----------------------------------
The previous ``todays_batch.csv`` carried a hand-frozen ``status`` column. Each
flight's EXPIRED / EXPIRING marker was computed *once* (against a reference
"today" of 2026-06-06) and then never recomputed, so the file silently went
stale: by 2026-06-08 several rows still read "EXPIRING" when their FR24 track
had already aged past the 365-day retention cliff and become unrecoverable.

``compute_status()`` below is the auto-updating fix: status is derived from
``date.today()`` (or an injected ``today``) against FR24's retention window on
every run, so a flight that crosses the cliff is reclassified the same day.

Status semantics (FR24 Gold keeps ~365 days of granular playback):
    AVAILABLE  🟢  plenty of runway before the track expires
    EXPIRING   🔴  within EXPIRING_WINDOW_DAYS of the 365-day cliff — grab now
    EXPIRED    ⛔  older than retention — track no longer downloadable, skip
    HARVESTED  ✅  already captured in ground_truth.sqlite — done, skip

The worklist is sourced from the operator's 2025 Flight Log, reconciled against
already-harvested flights, ordered by the depth-first plan (finish N196DM, then
N5854Z, then everything else), with the most-urgent-to-expire first, and capped
at the daily quota.

Planning only: this writes a CSV. It does not touch FR24 or download anything.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from parse_flight_log import parse as parse_flight_log  # noqa: E402

# ---- policy knobs ----------------------------------------------------------
RETENTION_DAYS = 365          # FR24 Gold granular-track retention window
EXPIRING_WINDOW_DAYS = 21     # within this many days of the cliff -> EXPIRING
DAILY_QUOTA = 25              # FR24 Gold exports per day
# Depth-first harvest priority. Tails earlier in the list are exported first.
PRIORITY_TAILS = ["N196DM", "N5854Z"]
# Operator-log dates and FR24 UTC track dates drift (timezone, approximate log
# entries). A log flight is treated as already captured if a harvested track for
# the same tail falls within this many days of it.
HARVEST_MATCH_TOLERANCE_DAYS = 2

STATUS_ICON = {
    "AVAILABLE": "🟢 AVAILABLE",
    "EXPIRING": "🔴 EXPIRING",
    "EXPIRED": "⛔ EXPIRED",
    "HARVESTED": "✅ HARVESTED",
}


def compute_status(flight_d: date, today: date) -> str:
    """Auto-updating availability status for a flight's FR24 track.

    Recomputed from ``today`` on every call — this is the fix for the old
    frozen-status bug. Returns one of AVAILABLE / EXPIRING / EXPIRED.
    """
    days_old = (today - flight_d).days
    if days_old > RETENTION_DAYS:
        return "EXPIRED"
    if days_old >= RETENTION_DAYS - EXPIRING_WINDOW_DAYS:
        return "EXPIRING"
    return "AVAILABLE"


def days_to_expiry(flight_d: date, today: date) -> int:
    """Days until this flight's track falls off the 365-day cliff (neg = gone)."""
    return RETENTION_DAYS - (today - flight_d).days


def load_harvested(sqlite_path: Path) -> dict:
    """Map registration -> sorted list of harvested track dates (date objects)."""
    out: dict = {}
    if not sqlite_path.exists():
        return out
    con = sqlite3.connect(sqlite_path)
    try:
        rows = con.execute(
            "SELECT registration, substr(start_utc,1,10) "
            "FROM flight_track_features WHERE start_utc IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    for reg, d in rows:
        if reg and d:
            try:
                out.setdefault(reg, []).append(date.fromisoformat(d))
            except ValueError:
                continue
    for reg in out:
        out[reg].sort()
    return out


def _is_captured(tail: str, fd: date, harvested: dict) -> bool:
    """True if a harvested track for this tail is within tolerance of ``fd``."""
    for hd in harvested.get(tail, ()):  # small lists; linear scan is fine
        if abs((hd - fd).days) <= HARVEST_MATCH_TOLERANCE_DAYS:
            return True
    return False


def _event_datetime(row: dict) -> Optional[datetime]:
    raw = (row.get("at") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _priority_key(tail: str) -> int:
    try:
        return PRIORITY_TAILS.index(tail)
    except ValueError:
        return len(PRIORITY_TAILS)


def build_rows(xlsx_path: Path, sqlite_path: Path, today: date):
    harvested = load_harvested(sqlite_path)
    harvested_counts = {reg: len(v) for reg, v in harvested.items()}

    candidates: list[dict] = []
    for ev in parse_flight_log(xlsx_path):
        tail = (ev.get("registration") or "").strip()
        dtm = _event_datetime(ev)
        if not tail or dtm is None:
            continue
        fd = dtm.date()
        if _is_captured(tail, fd, harvested):
            status = "HARVESTED"
        else:
            status = compute_status(fd, today)
        candidates.append({
            "tail": tail,
            "date": fd.isoformat(),
            "time": dtm.strftime("%H:%M:%S"),
            "operator": (ev.get("operator") or "").strip(),
            "_status_raw": status,
            "days_to_expiry": days_to_expiry(fd, today),
            "_pri": _priority_key(tail),
        })

    # Per-tail completion: a tail whose captured tracks already cover (or exceed)
    # its still-downloadable log flights is COMPLETE and drops out of the queue.
    avail_per_tail: dict = {}
    for c in candidates:
        if c["_status_raw"] in ("EXPIRING", "AVAILABLE"):
            avail_per_tail[c["tail"]] = avail_per_tail.get(c["tail"], 0) + 1
    complete_tails = {
        t for t, n_open in avail_per_tail.items()
        if harvested_counts.get(t, 0) >= n_open
    }

    # Today's actionable worklist: still downloadable, not yet captured, and from
    # a tail that is not already complete.
    worklist = [
        c for c in candidates
        if c["_status_raw"] in ("EXPIRING", "AVAILABLE") and c["tail"] not in complete_tails
    ]
    # Order: priority tail, then soonest-to-expire (most urgent), then date.
    worklist.sort(key=lambda c: (c["_pri"], c["days_to_expiry"], c["date"], c["time"]))
    worklist = worklist[:DAILY_QUOTA]

    out = []
    for i, c in enumerate(worklist, start=1):
        out.append({
            "rank": i,
            "tail": c["tail"],
            "date": c["date"],
            "time": c["time"],
            "operator": c["operator"],
            "status": STATUS_ICON[c["_status_raw"]],
            "days_to_expiry": c["days_to_expiry"],
        })
    meta = {
        "harvested_counts": harvested_counts,
        "avail_per_tail": avail_per_tail,
        "complete_tails": sorted(complete_tails),
    }
    return out, candidates, meta


def summarize(candidates: list[dict]) -> dict:
    from collections import Counter
    by_status = Counter(c["_status_raw"] for c in candidates)
    return {k: by_status.get(k, 0) for k in ("AVAILABLE", "EXPIRING", "EXPIRED", "HARVESTED")}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["rank", "tail", "date", "time", "operator", "status", "days_to_expiry"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build today's FR24 harvest batch (auto-updating status)")
    ap.add_argument("--xlsx", default=str(REPO / "data/manual_logs/Flight Log 2025.xlsx"))
    ap.add_argument("--sqlite", default=str(REPO / "data/ground_truth/ground_truth.sqlite"))
    ap.add_argument("--output", default=str(REPO / "data/todays_batch.csv"))
    ap.add_argument("--today", default=None, help="override today (YYYY-MM-DD) for testing")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    rows, candidates, meta = build_rows(Path(args.xlsx), Path(args.sqlite), today)
    write_csv(Path(args.output), rows)

    counts = summarize(candidates)
    print(f"today={today}  retention={RETENTION_DAYS}d  expiring_window={EXPIRING_WINDOW_DAYS}d  quota={DAILY_QUOTA}")
    print(f"flight-log candidates: {counts}")
    print(f"complete tails (already fully captured): {meta['complete_tails']}")
    print(f"wrote {len(rows)} worklist rows -> {args.output}")
    if rows:
        from collections import Counter
        tail_counts = Counter(r['tail'] for r in rows)
        urgent = [r for r in rows if r['status'].startswith('🔴')]
        print(f"  worklist by tail: {dict(tail_counts)}")
        print(f"  EXPIRING (grab-now) in worklist: {len(urgent)}")


if __name__ == "__main__":
    main()
