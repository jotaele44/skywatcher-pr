#!/usr/bin/env python3
"""Legacy month-over-month change detection — NONCANONICAL/AUDIT_ONLY.

The historical calculation falls back to filename time, uses raw registration
identity, and interprets count changes without a closed observation-opportunity
or coverage denominator. It may run only via ``--audit-only`` and its outputs
are quarantined from canonical analytics.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def main() -> int:
    global OUTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--surge-z", type=float, default=2.0)
    ap.add_argument("--vanish-min-history", type=int, default=3)
    ap.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = ap.parse_args()
    audit_dir = enter_audit_only(
        analysis="change_detection", audit_only=args.audit_only, repo=REPO
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

    aircraft_rows = conn.execute(
        f"""
        SELECT a.registration, substr({timestamp_expression},1,7) AS yyyymm
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {timestamp_expression} IS NOT NULL
        """
    ).fetchall()
    poi_rows = conn.execute(
        f"""
        SELECT lp.normalized_label, substr({timestamp_expression},1,7) AS yyyymm
        FROM labeled_pins lp
        JOIN screenshots s ON s.screenshot_id = lp.screenshot_id
        WHERE lp.pin_type_guess != 'unknown_label_candidate'
          AND {timestamp_expression} IS NOT NULL
        """
    ).fetchall()

    aircraft_grid = defaultdict(Counter)
    for registration, month in aircraft_rows:
        if registration and month:
            aircraft_grid[registration][month] += 1
    poi_grid = defaultdict(Counter)
    for poi, month in poi_rows:
        if poi and month:
            poi_grid[poi][month] += 1
    all_months = sorted(
        {month for counts in aircraft_grid.values() for month in counts}
        | {month for counts in poi_grid.values() for month in counts}
    )

    def emit_rows(grid, label_field):
        output = []
        if not all_months:
            return output
        for entity, monthly in grid.items():
            counts = [monthly.get(month, 0) for month in all_months]
            mean = sum(counts) / len(counts)
            variance = sum((count - mean) ** 2 for count in counts) / max(
                len(counts), 1
            )
            standard_deviation = math.sqrt(variance) or 1.0
            active_months = [
                (month, count)
                for month, count in zip(all_months, counts, strict=False)
                if count > 0
            ]
            for index, month in enumerate(all_months):
                count = counts[index]
                previous = counts[index - 1] if index > 0 else 0
                delta = count - previous
                zscore = (count - mean) / standard_deviation
                if count == 0 and previous > 0:
                    flag = "vanished"
                elif count > 0 and previous == 0 and index > 0:
                    flag = (
                        "debut"
                        if active_months and active_months[0][0] == month
                        else "returned"
                    )
                elif zscore >= args.surge_z and count > 1:
                    flag = "surge"
                elif zscore <= -args.surge_z and count > 0:
                    flag = "decline"
                else:
                    flag = "stable"
                output.append(
                    {
                        label_field: entity,
                        "yyyymm": month,
                        "count": count,
                        "delta_vs_prev": delta,
                        "zscore_vs_self": round(zscore, 2),
                        "flag": flag,
                        "active_months_in_corpus": len(active_months),
                        "certification_state": "AUDIT_ONLY",
                    }
                )
        return output

    aircraft_monthly = emit_rows(aircraft_grid, "registration")
    poi_monthly = emit_rows(poi_grid, "poi")
    OUTS.mkdir(parents=True, exist_ok=True)

    aircraft_fields = [
        "registration",
        "yyyymm",
        "count",
        "delta_vs_prev",
        "zscore_vs_self",
        "flag",
        "active_months_in_corpus",
        "certification_state",
    ]
    with (OUTS / "audit_change_aircraft_monthly.csv").open(
        "w", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=aircraft_fields, quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(aircraft_monthly)

    poi_fields = [
        "poi",
        "yyyymm",
        "count",
        "delta_vs_prev",
        "zscore_vs_self",
        "flag",
        "active_months_in_corpus",
        "certification_state",
    ]
    with (OUTS / "audit_change_poi_monthly.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=poi_fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(poi_monthly)

    alerts = []
    for row in aircraft_monthly:
        if row["flag"] == "surge":
            alerts.append({"kind": "aircraft_surge", "entity": row["registration"], **row})
        elif (
            row["flag"] == "vanished"
            and row["active_months_in_corpus"] >= args.vanish_min_history
        ):
            alerts.append(
                {"kind": "aircraft_vanished", "entity": row["registration"], **row}
            )
        elif row["flag"] == "debut" and row["count"] >= 3:
            alerts.append({"kind": "aircraft_debut", "entity": row["registration"], **row})
    for row in poi_monthly:
        if row["flag"] == "surge" and row["count"] >= 5:
            alerts.append({"kind": "poi_surge", "entity": row["poi"], **row})
        elif row["flag"] == "debut" and row["count"] >= 3:
            alerts.append({"kind": "poi_debut", "entity": row["poi"], **row})
    alerts.sort(key=lambda row: (row["yyyymm"], -row["count"]))

    with (OUTS / "audit_change_alerts.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            [
                "kind",
                "entity",
                "yyyymm",
                "count",
                "delta_vs_prev",
                "zscore",
                "flag",
                "certification_state",
            ]
        )
        for alert in alerts:
            writer.writerow(
                [
                    alert["kind"],
                    alert["entity"],
                    alert["yyyymm"],
                    alert["count"],
                    alert["delta_vs_prev"],
                    alert["zscore_vs_self"],
                    alert["flag"],
                    "AUDIT_ONLY",
                ]
            )

    conn.close()
    result = {
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY",
        "months_analyzed": all_months,
        "aircraft_tracked": len(aircraft_grid),
        "pois_tracked": len(poi_grid),
        "aircraft_alerts": sum(
            alert["kind"].startswith("aircraft") for alert in alerts
        ),
        "poi_alerts": sum(alert["kind"].startswith("poi") for alert in alerts),
        "outputs": [
            str((OUTS / "audit_change_aircraft_monthly.csv").relative_to(REPO)),
            str((OUTS / "audit_change_poi_monthly.csv").relative_to(REPO)),
            str((OUTS / "audit_change_alerts.csv").relative_to(REPO)),
        ],
    }
    (OUTS / "audit_change_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
