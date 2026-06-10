#!/usr/bin/env python3
"""
Phase E: Change detection — month-over-month operational dynamics.

For each (aircraft, month) and each (POI, month):
  - sightings count
  - z-score vs the aircraft's / POI's own historical baseline
  - month-over-month delta
  - flag = "new appearance" | "disappeared" | "surge" | "vanished" | "stable"

Outputs:
  - outputs/intel_change_aircraft_monthly.csv   per-aircraft month trends
  - outputs/intel_change_poi_monthly.csv         per-POI month trends
  - outputs/intel_change_alerts.csv              high-signal events (surges, vanishes, debuts)
  - outputs/intel_change_summary.md              narrative

CLI:
    python3 scripts/rlsm_change_detection.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--surge-z", type=float, default=2.0)
    ap.add_argument("--vanish-min-history", type=int, default=3,
                    help="aircraft needs ≥ this many active months before a vanish is alertable")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    ts_expr = "COALESCE(s.true_flight_ts, s.filename_ts)" if "true_flight_ts" in cols else "s.filename_ts"

    # All (registration, month_bucket) sightings — derive month from ts_expr
    rows = conn.execute(f"""
        SELECT a.registration, substr({ts_expr},1,7) AS yyyymm
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
    """).fetchall()

    poi_rows = conn.execute(f"""
        SELECT lp.normalized_label, substr({ts_expr},1,7) AS yyyymm
        FROM labeled_pois lp
        JOIN screenshots s ON s.screenshot_id = lp.screenshot_id
        WHERE lp.poi_type_guess != 'unknown_label_candidate'
          AND {ts_expr} IS NOT NULL
    """).fetchall()

    # Build monthly grids
    air_grid = defaultdict(Counter)   # reg -> {yyyymm: count}
    for reg, m in rows:
        if reg and m: air_grid[reg][m] += 1
    poi_grid = defaultdict(Counter)
    for poi, m in poi_rows:
        if poi and m: poi_grid[poi][m] += 1

    all_months = sorted({m for c in air_grid.values() for m in c} |
                        {m for c in poi_grid.values() for m in c})

    def emit_rows(grid, label_field):
        out = []
        for entity, monthly in grid.items():
            counts = [monthly.get(m, 0) for m in all_months]
            mean = sum(counts) / len(counts)
            var = sum((c - mean) ** 2 for c in counts) / max(len(counts), 1)
            std = math.sqrt(var) or 1.0
            active_months = [(m, c) for m, c in zip(all_months, counts) if c > 0]
            for i, m in enumerate(all_months):
                c = counts[i]
                prev = counts[i - 1] if i > 0 else 0
                delta = c - prev
                z = (c - mean) / std
                if c == 0 and prev > 0:
                    flag = "vanished"
                elif c > 0 and prev == 0 and i > 0:
                    flag = "debut" if active_months and active_months[0][0] == m else "returned"
                elif z >= args.surge_z and c > 1:
                    flag = "surge"
                elif z <= -args.surge_z and c > 0:
                    flag = "decline"
                else:
                    flag = "stable"
                out.append({
                    label_field: entity, "yyyymm": m, "count": c,
                    "delta_vs_prev": delta, "zscore_vs_self": round(z, 2),
                    "flag": flag,
                    "active_months_in_corpus": len(active_months),
                })
        return out

    air_monthly = emit_rows(air_grid, "registration")
    poi_monthly = emit_rows(poi_grid, "poi")

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_change_aircraft_monthly.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registration","yyyymm","count","delta_vs_prev",
                                           "zscore_vs_self","flag","active_months_in_corpus"],
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in air_monthly: w.writerow(r)
    with (OUTS / "intel_change_poi_monthly.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["poi","yyyymm","count","delta_vs_prev",
                                           "zscore_vs_self","flag","active_months_in_corpus"],
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in poi_monthly: w.writerow(r)

    # Alerts table: surges, vanishes (with sufficient history), debuts of meaningful aircraft
    alerts = []
    for r in air_monthly:
        if r["flag"] == "surge":
            alerts.append({"kind": "aircraft_surge", "entity": r["registration"], **r})
        elif r["flag"] == "vanished" and r["active_months_in_corpus"] >= args.vanish_min_history:
            alerts.append({"kind": "aircraft_vanished", "entity": r["registration"], **r})
        elif r["flag"] == "debut" and r["count"] >= 3:
            alerts.append({"kind": "aircraft_debut", "entity": r["registration"], **r})
    for r in poi_monthly:
        if r["flag"] == "surge" and r["count"] >= 5:
            alerts.append({"kind": "poi_surge", "entity": r["poi"], **r})
        elif r["flag"] == "debut" and r["count"] >= 3:
            alerts.append({"kind": "poi_debut", "entity": r["poi"], **r})

    alerts.sort(key=lambda x: (x["yyyymm"], -x["count"]))
    with (OUTS / "intel_change_alerts.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["kind","entity","yyyymm","count","delta_vs_prev","zscore","flag"])
        for a in alerts:
            w.writerow([a["kind"], a["entity"], a["yyyymm"], a["count"],
                        a["delta_vs_prev"], a["zscore_vs_self"], a["flag"]])

    # Narrative summary
    from collections import Counter as C
    by_kind_month = C((a["kind"], a["yyyymm"]) for a in alerts)
    md = ["# RLSM change detection — month-over-month dynamics\n",
          f"Months analyzed: **{', '.join(all_months)}**\n",
          f"Aircraft alerts: **{sum(1 for a in alerts if a['kind'].startswith('aircraft'))}**",
          f"\nPOI alerts: **{sum(1 for a in alerts if a['kind'].startswith('poi'))}**\n",
          "\n## Alert volume by kind & month\n",
          "| kind | " + " | ".join(all_months) + " |",
          "|---|" + "|".join(["---"] * len(all_months)) + "|"]
    for kind in ["aircraft_surge","aircraft_vanished","aircraft_debut","poi_surge","poi_debut"]:
        row = f"| {kind} |"
        for m in all_months:
            row += f" {by_kind_month.get((kind, m), 0)} |"
        md.append(row)
    md.append("\n## Top 30 alerts by recency × magnitude\n")
    md.append("| Month | Kind | Entity | Count | Δ vs prev | z |")
    md.append("|---|---|---|---|---|---|")
    for a in alerts[-30:][::-1]:
        md.append(f"| {a['yyyymm']} | {a['kind']} | {a['entity']} | {a['count']} | "
                  f"{a['delta_vs_prev']:+d} | {a['zscore_vs_self']:+.1f} |")
    (OUTS / "intel_change_summary.md").write_text("\n".join(md) + "\n")

    conn.close()
    print(json.dumps({
        "months_analyzed":     all_months,
        "aircraft_tracked":    len(air_grid),
        "pois_tracked":        len(poi_grid),
        "aircraft_alerts":     sum(1 for a in alerts if a["kind"].startswith("aircraft")),
        "poi_alerts":          sum(1 for a in alerts if a["kind"].startswith("poi")),
        "outputs": [
            "outputs/intel_change_aircraft_monthly.csv",
            "outputs/intel_change_poi_monthly.csv",
            "outputs/intel_change_alerts.csv",
            "outputs/intel_change_summary.md",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
