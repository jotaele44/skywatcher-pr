#!/usr/bin/env python3
"""Legacy empirical forecast — NONCANONICAL/AUDIT_ONLY.

The historical forecast falls back to filename capture time, accepts raw
registration identity, and does not normalize by observation opportunity or
coverage. It remains available only for diagnostic comparison via
``--audit-only`` and cannot produce canonical forecast artifacts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_ts(value):
    if not value or len(value) < 16:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> int:
    global OUTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-weeks", type=int, default=12)
    ap.add_argument("--forecast-days", type=int, default=7)
    ap.add_argument("--top-aircraft", type=int, default=30)
    ap.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = ap.parse_args()
    audit_dir = enter_audit_only(
        analysis="predictive", audit_only=args.audit_only, repo=REPO
    )
    if audit_dir is None:
        return 2
    OUTS = audit_dir

    conn = sqlite3.connect(DB)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(screenshots)")}
    timestamp_expression = (
        "COALESCE(s.true_flight_ts, s.filename_ts)"
        if "true_flight_ts" in columns
        else "s.filename_ts"
    )
    max_ts_row = conn.execute(
        f"""SELECT MAX({timestamp_expression})
            FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)"""
    ).fetchone()
    if not max_ts_row or not max_ts_row[0]:
        conn.close()
        print(json.dumps({"classification": "NONCANONICAL", "status": "NO_DATA"}))
        return 0
    max_dt = parse_ts(max_ts_row[0])
    if max_dt is None:
        conn.close()
        print(json.dumps({"classification": "NONCANONICAL", "status": "NO_VALID_TIME"}))
        return 0
    start_lookback = max_dt - timedelta(weeks=args.lookback_weeks)

    rows = conn.execute(
        f"""
        SELECT a.registration, {timestamp_expression} AS ts
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {timestamp_expression} IS NOT NULL
          AND {timestamp_expression} >= ?
        """,
        (start_lookback.isoformat(),),
    ).fetchall()
    counts = Counter(row[0] for row in rows)
    top_regs = [registration for registration, _count in counts.most_common(args.top_aircraft)]

    hour_bucket_size = 3
    cells = defaultdict(int)
    for registration, timestamp in rows:
        if registration not in top_regs:
            continue
        parsed = parse_ts(timestamp)
        if not parsed:
            continue
        hour_bucket = (parsed.hour // hour_bucket_size) * hour_bucket_size
        cells[(registration, parsed.weekday(), hour_bucket)] += 1

    weeks = args.lookback_weeks
    today = (max_dt + timedelta(days=1)).date()
    forecast_rows = []
    for offset in range(args.forecast_days):
        date = today + timedelta(days=offset)
        dow = date.weekday()
        for registration in top_regs:
            for hour_bucket in range(0, 24, hour_bucket_size):
                hits = cells.get((registration, dow, hour_bucket), 0)
                if hits == 0:
                    continue
                expected = hits / weeks
                if expected < 0.25:
                    continue
                forecast_rows.append(
                    {
                        "date": date.isoformat(),
                        "dow": DOW_NAMES[dow],
                        "hour_bucket": f"{hour_bucket:02d}-{hour_bucket + hour_bucket_size:02d}",
                        "registration": registration,
                        "expected_sightings": round(expected, 2),
                        "based_on_hits": hits,
                        "lookback_weeks": weeks,
                        "certification_state": "AUDIT_ONLY",
                    }
                )
    forecast_rows.sort(key=lambda row: (row["date"], -row["expected_sightings"]))

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = [
        "date",
        "dow",
        "hour_bucket",
        "registration",
        "expected_sightings",
        "based_on_hits",
        "lookback_weeks",
        "certification_state",
    ]
    with (OUTS / "audit_forecast_7day.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(forecast_rows)

    daily_sum = defaultdict(float)
    for row in forecast_rows:
        daily_sum[row["date"]] += row["expected_sightings"]
    summary = {
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY",
        "lookback_weeks": weeks,
        "max_corpus_ts": max_dt.isoformat(),
        "forecast_window": [
            today.isoformat(),
            (today + timedelta(days=args.forecast_days - 1)).isoformat(),
        ],
        "forecast_cells_emitted": len(forecast_rows),
        "daily_expected_sightings": dict(sorted(daily_sum.items())),
        "output": str((OUTS / "audit_forecast_7day.csv").relative_to(REPO)),
    }
    (OUTS / "audit_forecast_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    conn.close()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
