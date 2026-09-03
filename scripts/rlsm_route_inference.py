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

The clustering / sequence / recurrence logic lives in
``skywatcher.fpim.route_recurrence`` so the per-craft profile builder can reuse
it; this script is a thin CLI wrapper that preserves the original CSV outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

from skywatcher.fpim.route_recurrence import (  # noqa: E402
    MAX_ROUTE_POIS,
    cluster_flights,
    load_observation_rows,
    load_poi_index,
    recurring_routes,
    sequence_for_cluster,
    shape_of,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--min-route-repeat",
        type=int,
        default=3,
        help="A recurring route needs ≥ this many observations",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows = load_observation_rows(conn)
    poi_idx = load_poi_index(conn)
    clusters = cluster_flights(rows)

    # For each cluster, derive an ordered POI sequence + a route-sequence row.
    seq_rows = []
    route_counts: Counter = Counter()
    for c in clusters:
        seq = sequence_for_cluster(c, poi_idx)
        if not seq:
            continue
        shape = shape_of(seq)
        origin = c["origins"].most_common(1)[0][0] if c["origins"] else ""
        dest = c["destinations"].most_common(1)[0][0] if c["destinations"] else ""
        route_key = " → ".join(seq[:MAX_ROUTE_POIS])
        seq_rows.append(
            {
                "reg": c["reg"],
                "date": c["date"],
                "start_time": c["start"].strftime("%H:%M"),
                "end_time": c["end"].strftime("%H:%M"),
                "n_screenshots": len(c["sids"]),
                "operator": c["operator"] or "",
                "origin_iata": origin,
                "destination_iata": dest,
                "poi_sequence": route_key,
                "shape": shape,
            }
        )
        route_counts[(c["reg"], route_key, shape)] += 1

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
    with (OUTS / "intel_route_sequences.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in seq_rows:
            w.writerow(r)

    rec_rows = recurring_routes(route_counts, min_repeat=args.min_route_repeat)
    with (OUTS / "intel_recurring_routes.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["registration", "route_pattern", "shape", "n_observed"])
        for r in rec_rows:
            w.writerow(r)

    shape_counts = Counter(r["shape"] for r in seq_rows)
    conn.close()
    print(
        json.dumps(
            {
                "flight_clusters_total": len(clusters),
                "flight_clusters_with_poi_sequence": len(seq_rows),
                "shape_distribution": dict(shape_counts.most_common()),
                "unique_route_patterns": len(route_counts),
                "recurring_routes_emitted": len(rec_rows),
                "outputs": [
                    "outputs/intel_route_sequences.csv",
                    "outputs/intel_recurring_routes.csv",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
