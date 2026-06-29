#!/usr/bin/env python3
"""
Phase D: Cluster the 526,918 unlabeled POI candidates by recurring map position.

The original RLSM Phase 6 emitted candidate visual features (pads, tanks,
road scars, antennas, etc.) but never analyzed them. A real-world POI that
isn't labeled on the FR24 base map will show up as a candidate at *the same
map-pixel position* across many screenshots — only if it's a real persistent
feature. Random noise won't cluster.

Strategy:
  - Project each candidate's centroid (pixel x,y) into a screenshot-bounded
    coordinate space, then bucket-by-rounded-position
  - A "cluster" = a (rounded_x, rounded_y, candidate_type) bucket with N≥3 hits
    across DISTINCT screenshots
  - For each cluster, surface: candidate_type, recurrence count, distinct
    screenshots, aircraft visible during sightings, dominant DOW

Output:
  - outputs/intel_unlabeled_clusters.csv: top recurring unnamed features
  - outputs/intel_unlabeled_summary.md: human-readable

CLI:
    python3 scripts/rlsm_cluster_unlabeled_pois.py
    python3 scripts/rlsm_cluster_unlabeled_pois.py --grid-px 16 --min-recur 5
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-px", type=int, default=16,
                    help="Round centroid to this pixel grid (default 16; smaller=stricter)")
    ap.add_argument("--min-recur", type=int, default=5,
                    help="A cluster needs ≥ this many distinct screenshots (default 5)")
    ap.add_argument("--max-recur-pct", type=float, default=8.0,
                    help="Drop clusters that appear in >X%% of corpus (default 8%% — anything more is FR24 UI chrome)")
    ap.add_argument("--top-n", type=int, default=200, help="Emit top N clusters")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)

    rows = conn.execute("""
        SELECT u.candidate_id, u.screenshot_id, u.candidate_type,
               u.centroid_x, u.centroid_y, u.bbox_w, u.bbox_h, u.confidence,
               s.filename_ts, s.month_bucket, s.width AS sw, s.height AS sh
        FROM unlabeled_pin_candidates u
        JOIN screenshots s USING(screenshot_id)
        WHERE u.centroid_x IS NOT NULL AND u.centroid_y IS NOT NULL
    """).fetchall()

    print(f"[unlabeled-cluster] loaded {len(rows):,} candidates")

    # Group by (rounded_x, rounded_y, candidate_type) — only screenshots of the same
    # dimensions can be compared in pixel coordinates, so include dims in the key.
    grid = args.grid_px
    buckets = defaultdict(list)
    for r in rows:
        cid, sid, ctype, cx, cy, bw, bh, conf, ts, month, sw, sh = r
        if not sw or not sh:
            continue
        gx = (cx // grid) * grid
        gy = (cy // grid) * grid
        key = (sw, sh, ctype, gx, gy)
        buckets[key].append({
            "candidate_id": cid, "sid": sid, "ts": ts, "month": month,
            "bw": bw, "bh": bh, "conf": conf,
        })

    print(f"[unlabeled-cluster] formed {len(buckets):,} positional buckets")

    # Filter clusters by distinct-screenshots threshold
    aircraft_idx = defaultdict(list)  # screenshot_id -> [reg]
    for r in conn.execute("""
        SELECT screenshot_id, registration FROM aircraft_observations
        WHERE registration IS NOT NULL
    """):
        aircraft_idx[r[0]].append(r[1])

    # Compute total screenshots per (sw, sh) dimension to support the max-recur-pct filter
    total_by_dims = Counter()
    for r in conn.execute("SELECT width, height, COUNT(*) FROM screenshots GROUP BY width, height"):
        total_by_dims[(r[0], r[1])] = r[2]

    clusters = []
    rejected_chrome = rejected_outside_map = 0
    for (sw, sh, ctype, gx, gy), entries in buckets.items():
        distinct_sids = {e["sid"] for e in entries}
        if len(distinct_sids) < args.min_recur:
            continue
        # Filter UI chrome: anything appearing in too-high % of its dimension's screenshots
        total_for_dims = total_by_dims.get((sw, sh), 0)
        if total_for_dims:
            recur_pct = 100.0 * len(distinct_sids) / total_for_dims
            if recur_pct > args.max_recur_pct:
                rejected_chrome += 1
                continue
        # Exclude positions outside the actual map area (top status + nav, bottom card)
        # For 1170x2532: keep 320 <= y <= 1500 (inside the 12-65% map zone, with 80px buffer)
        # Generalize: keep within 13–62% of image height
        if sh:
            y_pct = gy / sh
            if y_pct < 0.13 or y_pct > 0.62:
                rejected_outside_map += 1
                continue
        # Aggregate metadata
        months = Counter(e["month"] for e in entries if e["month"])
        ts_sorted = sorted(e["ts"] for e in entries if e["ts"])
        confs = [e["conf"] for e in entries if e["conf"] is not None]
        # Aircraft seen across these screenshots
        aircraft_seen = Counter()
        for sid in distinct_sids:
            for reg in aircraft_idx.get(sid, []):
                aircraft_seen[reg] += 1
        clusters.append({
            "cluster_key": f"{sw}x{sh}_{ctype}_{gx}_{gy}",
            "image_dims": f"{sw}x{sh}",
            "candidate_type": ctype,
            "grid_x_px": gx, "grid_y_px": gy,
            "n_hits": len(entries),
            "n_distinct_screenshots": len(distinct_sids),
            "first_seen": ts_sorted[0] if ts_sorted else None,
            "last_seen":  ts_sorted[-1] if ts_sorted else None,
            "months_active": ",".join(sorted(months)),
            "avg_confidence": round(sum(confs) / max(len(confs), 1), 2) if confs else None,
            "top_aircraft": ",".join(f"{r}({n})" for r, n in aircraft_seen.most_common(3)),
            "n_unique_aircraft": len(aircraft_seen),
        })

    clusters.sort(key=lambda c: -c["n_distinct_screenshots"])
    print(f"[unlabeled-cluster] emitting {min(len(clusters), args.top_n)} of {len(clusters)} clusters above threshold")

    OUTS.mkdir(parents=True, exist_ok=True)
    fields = ["cluster_key", "image_dims", "candidate_type",
              "grid_x_px", "grid_y_px",
              "n_hits", "n_distinct_screenshots",
              "first_seen", "last_seen", "months_active",
              "avg_confidence", "top_aircraft", "n_unique_aircraft"]
    with (OUTS / "intel_unlabeled_clusters.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL,
                           extrasaction='ignore')
        w.writeheader()
        for c in clusters[:args.top_n]:
            w.writerow(c)

    # By candidate-type rollup
    by_type = Counter()
    for c in clusters:
        by_type[c["candidate_type"]] += 1

    md = [f"# Unlabeled POI clusters — recurring map features without names\n",
          f"Generated: {_iso_now()}\n",
          f"\n**Source**: {len(rows):,} raw unlabeled candidates from Phase 6 vision pass.",
          f"\n**Method**: bucket centroids by {grid}-pixel grid, keep buckets with ≥ {args.min_recur} distinct screenshots.",
          f"\n**Result**: {len(clusters):,} persistent recurring positional clusters.\n",
          "\n## Candidate-type breakdown (recurring clusters only)\n",
          "| candidate_type | recurring clusters |", "|---|---|"]
    for t, n in by_type.most_common():
        md.append(f"| {t} | {n} |")
    md += ["\n## Top 30 by distinct-screenshot recurrence\n",
           "| Type | Image | Pixel | Distinct screenshots | Months active | Top aircraft |",
           "|---|---|---|---|---|---|"]
    for c in clusters[:30]:
        md.append(f"| {c['candidate_type']} | {c['image_dims']} | "
                  f"({c['grid_x_px']},{c['grid_y_px']}) | "
                  f"{c['n_distinct_screenshots']} | {c['months_active'][:40]} | "
                  f"{c['top_aircraft'][:50]} |")
    (OUTS / "intel_unlabeled_summary.md").write_text("\n".join(md) + "\n")

    conn.close()
    print(json.dumps({
        "raw_candidates_loaded": len(rows),
        "positional_buckets": len(buckets),
        "recurring_clusters_after_filter": len(clusters),
        "rejected_as_ui_chrome": rejected_chrome,
        "emitted_top_n": min(len(clusters), args.top_n),
        "by_candidate_type": dict(by_type.most_common()),
        "outputs": [
            "outputs/intel_unlabeled_clusters.csv",
            "outputs/intel_unlabeled_summary.md",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
