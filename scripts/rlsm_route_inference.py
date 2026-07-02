#!/usr/bin/env python3
"""
Phase C: Route inference.

For each flight cluster (same tail + same date + sightings within 60 min gap),
derive the actual POI visit sequence by ordering labeled POIs by their
true_flight_ts. Then surface recurring multi-POI routes for each aircraft.

Outputs:
  - outputs/intel_route_sequences.csv     one row per (tail, date) flight cluster
                                          with ordered POI sequence + O/D from side-mining
  - outputs/intel_recurring_routes.csv    routes observed ≥ 3 times across the
                                          corpus (the canonical patterns)

CLI:
    python3 scripts/rlsm_route_inference.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def parse_ts(s):
    if not s or len(s) < 16: return None
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None


def shape_of(sequence: list[str]) -> str:
    """Classify a POI sequence as loop, linear, hub-and-spoke, or single-point."""
    if not sequence: return "absent"
    if len(sequence) == 1: return "single_poi"
    if len(set(sequence)) == 1: return "stationary"
    # Loop: returns to first POI
    if sequence[0] == sequence[-1] and len(sequence) >= 3:
        return "loop"
    # Out-and-back: A-B-A pattern of length 3
    if len(sequence) == 3 and sequence[0] == sequence[2] and sequence[0] != sequence[1]:
        return "out_and_back"
    # Hub-and-spoke: one POI appears in >50% of positions
    counts = Counter(sequence)
    most_common = counts.most_common(1)[0]
    if most_common[1] / len(sequence) > 0.5:
        return "hub_and_spoke"
    return "linear" if len(set(sequence)) == len(sequence) else "multi_visit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-route-repeat", type=int, default=3,
                    help="A recurring route needs ≥ this many observations")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    ts_expr = "COALESCE(s.true_flight_ts, s.filename_ts)" if "true_flight_ts" in cols else "s.filename_ts"
    has_side = "origin_iata" in {r[1] for r in conn.execute("PRAGMA table_info(aircraft_observations)")}

    # Pull every (aircraft_obs, ts) + the labeled POIs visible in that screenshot
    rows = conn.execute(f"""
        SELECT a.registration, {ts_expr} AS ts, a.screenshot_id,
               a.origin_iata, a.destination_iata,
               a.operator_text_manual
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
        ORDER BY a.registration, ts
    """ if has_side else f"""
        SELECT a.registration, {ts_expr} AS ts, a.screenshot_id,
               NULL AS origin_iata, NULL AS destination_iata,
               a.operator_text_manual
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
        ORDER BY a.registration, ts
    """).fetchall()

    poi_idx = defaultdict(list)
    for r in conn.execute("""
        SELECT screenshot_id, normalized_label, pin_type_guess
        FROM labeled_pins
        WHERE pin_type_guess != 'unknown_label_candidate'
    """):
        poi_idx[r[0]].append(r[1])

    # Cluster into flight events: same reg, same date, gap ≤ 60 min
    from datetime import timedelta
    clusters = []
    cur_cluster = None
    prev = None
    for reg, ts, sid, oia, dia, op in rows:
        dt = parse_ts(ts)
        if not dt: continue
        if cur_cluster is None:
            cur_cluster = {"reg": reg, "date": dt.date().isoformat(),
                           "start": dt, "end": dt, "sids": [sid],
                           "origins": Counter(), "destinations": Counter(),
                           "operator": op}
        else:
            same_day_same_reg = (cur_cluster["reg"] == reg and
                                  cur_cluster["date"] == dt.date().isoformat())
            within_gap = (dt - cur_cluster["end"]) <= timedelta(minutes=60)
            if same_day_same_reg and within_gap:
                cur_cluster["end"] = dt
                cur_cluster["sids"].append(sid)
            else:
                clusters.append(cur_cluster)
                cur_cluster = {"reg": reg, "date": dt.date().isoformat(),
                               "start": dt, "end": dt, "sids": [sid],
                               "origins": Counter(), "destinations": Counter(),
                               "operator": op}
        if oia: cur_cluster["origins"][oia] += 1
        if dia: cur_cluster["destinations"][dia] += 1
        prev = (reg, dt)
    if cur_cluster:
        clusters.append(cur_cluster)

    # For each cluster, derive an ordered POI sequence (dedup consecutive duplicates)
    seq_rows = []
    route_counts = Counter()
    for c in clusters:
        seq_raw = []
        for sid in c["sids"]:
            for poi in poi_idx.get(sid, []):
                if not seq_raw or seq_raw[-1] != poi:
                    seq_raw.append(poi)
        # Compress: keep maximal-distinct sequence
        seq = []
        for poi in seq_raw:
            if not seq or seq[-1] != poi:
                seq.append(poi)
        if not seq:
            continue
        shape = shape_of(seq)
        origin = c["origins"].most_common(1)[0][0] if c["origins"] else ""
        dest   = c["destinations"].most_common(1)[0][0] if c["destinations"] else ""
        route_key = " → ".join(seq[:8])
        seq_rows.append({
            "reg": c["reg"], "date": c["date"],
            "start_time": c["start"].strftime("%H:%M"),
            "end_time": c["end"].strftime("%H:%M"),
            "n_screenshots": len(c["sids"]),
            "operator": c["operator"] or "",
            "origin_iata": origin, "destination_iata": dest,
            "poi_sequence": route_key,
            "shape": shape,
        })
        route_counts[(c["reg"], route_key, shape)] += 1

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = ["reg","date","start_time","end_time","n_screenshots","operator",
              "origin_iata","destination_iata","poi_sequence","shape"]
    with (OUTS / "intel_route_sequences.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in seq_rows:
            w.writerow(r)

    # Recurring routes
    rec_rows = [(reg, route, shape, n) for (reg, route, shape), n
                in sorted(route_counts.items(), key=lambda x: -x[1])
                if n >= args.min_route_repeat]
    with (OUTS / "intel_recurring_routes.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["registration", "route_pattern", "shape", "n_observed"])
        for r in rec_rows:
            w.writerow(r)

    # Shape distribution
    shape_counts = Counter(r["shape"] for r in seq_rows)
    conn.close()
    print(json.dumps({
        "flight_clusters_total": len(clusters),
        "flight_clusters_with_poi_sequence": len(seq_rows),
        "shape_distribution": dict(shape_counts.most_common()),
        "unique_route_patterns": len(route_counts),
        "recurring_routes_emitted": len(rec_rows),
        "outputs": [
            "outputs/intel_route_sequences.csv",
            "outputs/intel_recurring_routes.csv",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
