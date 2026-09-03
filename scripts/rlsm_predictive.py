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

The (dow, hour_bucket) cell + forecast logic lives in
``skywatcher.fpim.schedule`` so the per-craft profile builder can reuse it;
this script is a thin CLI wrapper that preserves the original outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

from skywatcher.fpim.schedule import (  # noqa: E402
    HOUR_BUCKET_SIZE,
    build_cells,
    forecast_rows,
    load_observations,
    max_corpus_ts,
    top_registrations,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-weeks", type=int, default=12)
    ap.add_argument("--forecast-days", type=int, default=7)
    ap.add_argument("--top-aircraft", type=int, default=30)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    all_rows = load_observations(conn)
    max_dt = max_corpus_ts(all_rows)
    if max_dt is None:
        print("[forecast] no data")
        return

    start_lookback = max_dt - timedelta(weeks=args.lookback_weeks)
    rows = load_observations(conn, since=start_lookback.isoformat())

    top_regs = top_registrations(rows, args.top_aircraft)
    cells = build_cells(rows, keep_regs=set(top_regs))

    weeks = args.lookback_weeks
    today = (max_dt + timedelta(days=1)).date()
    fc_rows = forecast_rows(
        cells, top_regs, max_dt, weeks, args.forecast_days, hour_bucket_size=HOUR_BUCKET_SIZE
    )

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_forecast_7day.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "dow",
                "hour_bucket",
                "registration",
                "expected_sightings",
                "based_on_hits",
                "lookback_weeks",
            ],
            quoting=csv.QUOTE_ALL,
        )
        w.writeheader()
        for r in fc_rows:
            w.writerow(r)

    # Summary
    md = [
        "# RLSM 7-day operational forecast\n",
        f"Generated from {args.lookback_weeks}-week empirical baseline (last corpus date: {max_dt.date().isoformat()})\n",
        f"Forecast window: **{today.isoformat()} → {(today + timedelta(days=args.forecast_days - 1)).isoformat()}**\n",
        "\n## Top 30 high-probability cells\n",
        "| Date | DOW | Hour | Aircraft | Expected | Based on |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(fc_rows, key=lambda x: -x["expected_sightings"])[:30]:
        md.append(
            f"| {r['date']} | {r['dow']} | {r['hour_bucket']} | {r['registration']} | "
            f"{r['expected_sightings']} | {r['based_on_hits']} hits in {weeks} weeks |"
        )
    md.append("\n## Per-day expected sightings (sum over top aircraft)\n")
    md.append("| Date | DOW | Total expected sightings |")
    md.append("|---|---|---|")
    daily_sum = defaultdict(float)
    daily_dow = {}
    for r in fc_rows:
        daily_sum[r["date"]] += r["expected_sightings"]
        daily_dow[r["date"]] = r["dow"]
    for d in sorted(daily_sum):
        md.append(f"| {d} | {daily_dow[d]} | {daily_sum[d]:.1f} |")

    (OUTS / "intel_forecast_summary.md").write_text("\n".join(md) + "\n")
    conn.close()
    print(
        json.dumps(
            {
                "lookback_weeks": args.lookback_weeks,
                "max_corpus_ts": max_dt.isoformat(),
                "forecast_window": [
                    today.isoformat(),
                    (today + timedelta(days=args.forecast_days - 1)).isoformat(),
                ],
                "top_aircraft": top_regs[:10],
                "forecast_cells_emitted": len(fc_rows),
                "outputs": ["outputs/intel_forecast_7day.csv", "outputs/intel_forecast_summary.md"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
