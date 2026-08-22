#!/usr/bin/env python3
"""Legacy route inference — NONCANONICAL/AUDIT_ONLY.

The historical calculation is preserved for diagnostics, but it treats
screen-visible POI labels as aircraft visits/endpoints and falls back to
filename capture time. Those semantics are forbidden for canonical analysis.
Use ``--audit-only`` to run the historical calculation in a quarantined output
directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def parse_ts(s):
    if not s or len(s) < 16:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def shape_of(sequence: list[str]) -> str:
    """Classify a POI sequence as loop, linear, hub-and-spoke, or single-point."""
    if not sequence:
        return "absent"
    if len(sequence) == 1:
        return "single_poi"
    if len(set(sequence)) == 1:
        return "stationary"
    if sequence[0] == sequence[-1] and len(sequence) >= 3:
        return "loop"
    if len(sequence) == 3 and sequence[0] == sequence[2] and sequence[0] != sequence[1]:
        return "out_and_back"
    counts = Counter(sequence)
    most_common = counts.most_common(1)[0]
    if most_common[1] / len(sequence) > 0.5:
        return "hub_and_spoke"
    return "linear" if len(set(sequence)) == len(sequence) else "multi_visit"


def main() -> int:
    global OUTS
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--min-route-repeat",
        type=int,
        default=3,
        help="A recurring route needs ≥ this many observations",
    )
    ap.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = ap.parse_args()
    audit_dir = enter_audit_only(
        analysis="route_inference", audit_only=args.audit_only, repo=REPO
    )
    if audit_dir is None:
        return 2
    OUTS = audit_dir

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    ts_expr = (
        "COALESCE(s.true_flight_ts, s.filename_ts)"
        if "true_flight_ts" in cols
        else "s.filename_ts"
    )
    has_side = "origin_iata" in {
        r[1] for r in conn.execute("PRAGMA table_info(aircraft_observations)")
    }

    rows = conn.execute(
        f"""
        SELECT a.registration, {ts_expr} AS ts, a.screenshot_id,
               a.origin_iata, a.destination_iata,
               a.operator_text_manual
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
        ORDER BY a.registration, ts
    """
        if has_side
        else f"""
        SELECT a.registration, {ts_expr} AS ts, a.screenshot_id,
               NULL AS origin_iata, NULL AS destination_iata,
               a.operator_text_manual
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
        ORDER BY a.registration, ts
    """
    ).fetchall()

    poi_idx = defaultdict(list)
    for row in conn.execute(
        """
        SELECT screenshot_id, normalized_label, pin_type_guess
        FROM labeled_pins
        WHERE pin_type_guess != 'unknown_label_candidate'
    """
    ):
        poi_idx[row[0]].append(row[1])

    from datetime import timedelta

    clusters = []
    cur_cluster = None
    for reg, ts, sid, origin_iata, destination_iata, operator in rows:
        dt = parse_ts(ts)
        if not dt:
            continue
        if cur_cluster is None:
            cur_cluster = {
                "reg": reg,
                "date": dt.date().isoformat(),
                "start": dt,
                "end": dt,
                "sids": [sid],
                "origins": Counter(),
                "destinations": Counter(),
                "operator": operator,
            }
        else:
            same_day_same_reg = (
                cur_cluster["reg"] == reg
                and cur_cluster["date"] == dt.date().isoformat()
            )
            within_gap = (dt - cur_cluster["end"]) <= timedelta(minutes=60)
            if same_day_same_reg and within_gap:
                cur_cluster["end"] = dt
                cur_cluster["sids"].append(sid)
            else:
                clusters.append(cur_cluster)
                cur_cluster = {
                    "reg": reg,
                    "date": dt.date().isoformat(),
                    "start": dt,
                    "end": dt,
                    "sids": [sid],
                    "origins": Counter(),
                    "destinations": Counter(),
                    "operator": operator,
                }
        if origin_iata:
            cur_cluster["origins"][origin_iata] += 1
        if destination_iata:
            cur_cluster["destinations"][destination_iata] += 1
    if cur_cluster:
        clusters.append(cur_cluster)

    seq_rows = []
    route_counts = Counter()
    for cluster in clusters:
        seq_raw = []
        for sid in cluster["sids"]:
            for poi in poi_idx.get(sid, []):
                if not seq_raw or seq_raw[-1] != poi:
                    seq_raw.append(poi)
        sequence = []
        for poi in seq_raw:
            if not sequence or sequence[-1] != poi:
                sequence.append(poi)
        if not sequence:
            continue
        shape = shape_of(sequence)
        origin = (
            cluster["origins"].most_common(1)[0][0] if cluster["origins"] else ""
        )
        destination = (
            cluster["destinations"].most_common(1)[0][0]
            if cluster["destinations"]
            else ""
        )
        route_key = " → ".join(sequence[:8])
        seq_rows.append(
            {
                "reg": cluster["reg"],
                "date": cluster["date"],
                "start_time": cluster["start"].strftime("%H:%M"),
                "end_time": cluster["end"].strftime("%H:%M"),
                "n_screenshots": len(cluster["sids"]),
                "operator": cluster["operator"] or "",
                "origin_iata": origin,
                "destination_iata": destination,
                "poi_sequence": route_key,
                "shape": shape,
            }
        )
        route_counts[(cluster["reg"], route_key, shape)] += 1

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = [
        "reg",
        "date",
        "start_time",
        "end_time",
        "n_screenshots",
        "operator",
        "origin_iata",
        "destination_iata",
        "poi_sequence",
        "shape",
    ]
    with (OUTS / "audit_route_sequences.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in seq_rows:
            writer.writerow(row)

    recurring_rows = [
        (reg, route, shape, count)
        for (reg, route, shape), count in sorted(
            route_counts.items(), key=lambda item: -item[1]
        )
        if count >= args.min_route_repeat
    ]
    with (OUTS / "audit_recurring_routes.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["registration", "route_pattern", "shape", "n_observed"])
        writer.writerows(recurring_rows)

    shape_counts = Counter(row["shape"] for row in seq_rows)
    conn.close()
    print(
        json.dumps(
            {
                "classification": "NONCANONICAL",
                "certification_state": "AUDIT_ONLY",
                "flight_clusters_total": len(clusters),
                "flight_clusters_with_poi_sequence": len(seq_rows),
                "shape_distribution": dict(shape_counts.most_common()),
                "unique_route_patterns": len(route_counts),
                "recurring_routes_emitted": len(recurring_rows),
                "outputs": [
                    str((OUTS / "audit_route_sequences.csv").relative_to(REPO)),
                    str((OUTS / "audit_recurring_routes.csv").relative_to(REPO)),
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
