#!/usr/bin/env python3
"""Cluster-first review worklist (strategy #5).

Nobody reviews ~527k unlabeled pin candidates item by item — but
scripts/rlsm_cluster_unlabeled_pois.py already groups them by recurring
map-pixel position, so ONE review decision covers every recurrence in a
cluster. This ranker turns the cluster CSV into a prioritized worklist:
clusters that co-occur with high-confidence aircraft observations first,
then breadth (distinct screenshots) and persistence (months active).

Ranking score (deterministic, documented in the output):
    score = 3.0 * n_unique_aircraft        # aircraft co-occurrence dominates
          + 1.0 * n_distinct_screenshots   # breadth
          + 2.0 * months_active_count      # persistence across months
Ties break on cluster_key so re-runs are stable.

The printed footer names the SATIM follow-through — reviewed labels should
flow into the existing harvest -> refit loop rather than ad-hoc notes, so
every reviewing hour also un-starves the calibration engine (12 ground-truth
labels today).

Usage:
    python3 scripts/rlsm_review_worklist.py \
        [--clusters outputs/intel_unlabeled_clusters.csv] \
        [--out outputs/review_worklist.csv] [--top-n 50]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CLUSTERS = REPO / "outputs" / "intel_unlabeled_clusters.csv"
DEFAULT_OUT = REPO / "outputs" / "review_worklist.csv"

WEIGHT_AIRCRAFT = 3.0
WEIGHT_SCREENSHOTS = 1.0
WEIGHT_MONTHS = 2.0

OUT_FIELDS = [
    "rank", "review_score", "cluster_key", "candidate_type", "image_dims",
    "grid_x_px", "grid_y_px", "n_hits", "n_distinct_screenshots",
    "n_unique_aircraft", "months_active", "first_seen", "last_seen",
    "avg_confidence", "top_aircraft", "rationale",
]

SATIM_FOLLOW_THROUGH = """\
Review follow-through (label once, benefit twice):
  1. Record each cluster decision in the RLSM review queue / labeled_pins as
     usual — one decision covers every recurrence in the cluster.
  2. Feed the reviewed labels into the SATIM calibration loop (the engine is
     built but starved at ~12 ground-truth labels):
       python3 scripts/satim_harvest_review_labels.py
       python3 scripts/fit_satim_calibration.py
"""


def _as_int(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _months_count(months_active: str) -> int:
    return len([m for m in (months_active or "").split(",") if m.strip()])


def score_cluster(row: dict) -> float:
    return round(
        WEIGHT_AIRCRAFT * _as_int(row.get("n_unique_aircraft"))
        + WEIGHT_SCREENSHOTS * _as_int(row.get("n_distinct_screenshots"))
        + WEIGHT_MONTHS * _months_count(row.get("months_active", "")),
        2,
    )


def _rationale(row: dict) -> str:
    parts = []
    aircraft = _as_int(row.get("n_unique_aircraft"))
    if aircraft:
        parts.append(f"{aircraft} distinct aircraft co-occur")
    screenshots = _as_int(row.get("n_distinct_screenshots"))
    parts.append(f"recurs in {screenshots} screenshots")
    months = _months_count(row.get("months_active", ""))
    if months > 1:
        parts.append(f"persists across {months} months")
    confidence = _as_float(row.get("avg_confidence"))
    if confidence is not None:
        parts.append(f"avg detector confidence {confidence}")
    return "; ".join(parts)


def build_worklist(cluster_rows: List[dict], top_n: int) -> List[dict]:
    ranked = sorted(
        cluster_rows,
        key=lambda row: (-score_cluster(row), str(row.get("cluster_key", ""))),
    )
    worklist = []
    for rank, row in enumerate(ranked[:top_n], 1):
        entry = {field: row.get(field, "") for field in OUT_FIELDS
                 if field not in ("rank", "review_score", "rationale")}
        entry["rank"] = rank
        entry["review_score"] = score_cluster(row)
        entry["rationale"] = _rationale(row)
        worklist.append(entry)
    return worklist


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rank unlabeled-POI clusters into a review worklist."
    )
    ap.add_argument("--clusters", default=str(DEFAULT_CLUSTERS),
                    help="Cluster CSV from scripts/rlsm_cluster_unlabeled_pois.py")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--top-n", type=int, default=50)
    args = ap.parse_args(argv)

    clusters_path = Path(args.clusters)
    if not clusters_path.exists():
        print(f"FAIL — clusters CSV not found: {clusters_path}"
              f" (run scripts/rlsm_cluster_unlabeled_pois.py first)")
        return 1

    with clusters_path.open(newline="") as fh:
        cluster_rows = list(csv.DictReader(fh))
    worklist = build_worklist(cluster_rows, args.top_n)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        writer.writeheader()
        for entry in worklist:
            writer.writerow(entry)

    print(json.dumps({
        "clusters_in": len(cluster_rows),
        "worklist_out": len(worklist),
        "out": str(out_path),
        "weights": {
            "n_unique_aircraft": WEIGHT_AIRCRAFT,
            "n_distinct_screenshots": WEIGHT_SCREENSHOTS,
            "months_active": WEIGHT_MONTHS,
        },
    }, indent=2))
    print(SATIM_FOLLOW_THROUGH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
