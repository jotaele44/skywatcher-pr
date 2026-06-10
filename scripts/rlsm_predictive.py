#!/usr/bin/env python3
"""
Phase H: Predictive forecast.

For each top operator and each top POI:
  - Compute the per-aircraft empirical (DOW, hour_bucket) sightings rate over
    the last 12 weeks
  - Forecast the next 7 days as a probability/expected-sightings table
  - Output a "watchlist" of high-probability (entity, date, hour) cells

This is an empirical-baseline forecast — not a regression. It says "based on
recent behavior, here's where each aircraft is most likely to show up."

Outputs:
  - outputs/intel_forecast_7day.csv
  - outputs/intel_forecast_summary.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_ts(s):
    if not s or len(s) < 16: return None
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-weeks", type=int, default=12)
    ap.add_argument("--forecast-days", type=int, default=7)
    ap.add_argument("--top-aircraft", type=int, default=30)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    ts_expr = "COALESCE(s.true_flight_ts, s.filename_ts)" if "true_flight_ts" in cols else "s.filename_ts"

    # Find max date in corpus
    max_ts_row = conn.execute(f"SELECT MAX({ts_expr}) FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)").fetchone()
    if not max_ts_row or not max_ts_row[0]:
        print("[forecast] no data")
        return
    max_dt = parse_ts(max_ts_row[0])
    start_lookback = max_dt - timedelta(weeks=args.lookback_weeks)

    # Pull recent aircraft observations
    rows = conn.execute(f"""
        SELECT a.registration, {ts_expr} AS ts
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
          AND {ts_expr} >= ?
    """, (start_lookback.isoformat(),)).fetchall()

    # Top aircraft by recent volume
    counts = Counter(r[0] for r in rows)
    top_regs = [r for r, _ in counts.most_common(args.top_aircraft)]

    # Build (reg, dow, hour_bucket) -> rate per (lookback weeks)
    hour_bucket_size = 3
    cells = defaultdict(int)
    for reg, ts in rows:
        if reg not in top_regs: continue
        dt = parse_ts(ts)
        if not dt: continue
        dow = dt.weekday()
        hb = (dt.hour // hour_bucket_size) * hour_bucket_size
        cells[(reg, dow, hb)] += 1

    # Build forecast over next N days
    weeks = args.lookback_weeks  # cells / weeks = expected per-week
    today = (max_dt + timedelta(days=1)).date()
    forecast_rows = []
    for offset in range(args.forecast_days):
        d = today + timedelta(days=offset)
        dow = d.weekday()
        for reg in top_regs:
            for hb in range(0, 24, hour_bucket_size):
                hits = cells.get((reg, dow, hb), 0)
                if hits == 0: continue
                expected = hits / weeks
                if expected < 0.25: continue  # filter noise
                forecast_rows.append({
                    "date": d.isoformat(),
                    "dow": DOW_NAMES[dow],
                    "hour_bucket": f"{hb:02d}-{hb+hour_bucket_size:02d}",
                    "registration": reg,
                    "expected_sightings": round(expected, 2),
                    "based_on_hits": hits,
                    "lookback_weeks": weeks,
                })

    forecast_rows.sort(key=lambda r: (r["date"], -r["expected_sightings"]))

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_forecast_7day.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","dow","hour_bucket","registration",
                                           "expected_sightings","based_on_hits","lookback_weeks"],
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in forecast_rows: w.writerow(r)

    # Summary
    md = [f"# RLSM 7-day operational forecast\n",
          f"Generated from {args.lookback_weeks}-week empirical baseline (last corpus date: {max_dt.date().isoformat()})\n",
          f"Forecast window: **{today.isoformat()} → {(today + timedelta(days=args.forecast_days-1)).isoformat()}**\n",
          "\n## Top 30 high-probability cells\n",
          "| Date | DOW | Hour | Aircraft | Expected | Based on |",
          "|---|---|---|---|---|---|"]
    for r in sorted(forecast_rows, key=lambda x: -x["expected_sightings"])[:30]:
        md.append(f"| {r['date']} | {r['dow']} | {r['hour_bucket']} | {r['registration']} | "
                  f"{r['expected_sightings']} | {r['based_on_hits']} hits in {weeks} weeks |")
    md.append("\n## Per-day expected sightings (sum over top aircraft)\n")
    md.append("| Date | DOW | Total expected sightings |")
    md.append("|---|---|---|")
    daily_sum = defaultdict(float)
    daily_dow = {}
    for r in forecast_rows:
        daily_sum[r["date"]] += r["expected_sightings"]
        daily_dow[r["date"]] = r["dow"]
    for d in sorted(daily_sum):
        md.append(f"| {d} | {daily_dow[d]} | {daily_sum[d]:.1f} |")

    (OUTS / "intel_forecast_summary.md").write_text("\n".join(md) + "\n")
    conn.close()
    print(json.dumps({
        "lookback_weeks": args.lookback_weeks,
        "max_corpus_ts": max_dt.isoformat(),
        "forecast_window": [today.isoformat(),
                             (today + timedelta(days=args.forecast_days-1)).isoformat()],
        "top_aircraft": top_regs[:10],
        "forecast_cells_emitted": len(forecast_rows),
        "outputs": ["outputs/intel_forecast_7day.csv",
                    "outputs/intel_forecast_summary.md"],
    }, indent=2))


if __name__ == "__main__":
    main()
