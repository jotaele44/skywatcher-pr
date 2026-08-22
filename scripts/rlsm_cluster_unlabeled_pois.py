#!/usr/bin/env python3
"""Legacy raw-pixel unlabeled-POI clustering — NONCANONICAL/AUDIT_ONLY.

The historical implementation compares recurring pixel positions across
screenshots of the same dimensions without proving viewport equivalence.
Deterministic pixel recurrence is not persistent ground-feature identity.
Use ``--audit-only`` for diagnostic comparison; outputs are quarantined.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    global OUTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-px", type=int, default=16)
    ap.add_argument("--min-recur", type=int, default=5)
    ap.add_argument("--max-recur-pct", type=float, default=8.0)
    ap.add_argument("--top-n", type=int, default=200)
    ap.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = ap.parse_args()
    audit_dir = enter_audit_only(
        analysis="cluster_unlabeled_pois", audit_only=args.audit_only, repo=REPO
    )
    if audit_dir is None:
        return 2
    OUTS = audit_dir

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT u.candidate_id, u.screenshot_id, u.candidate_type,
               u.centroid_x, u.centroid_y, u.bbox_w, u.bbox_h, u.confidence,
               s.filename_ts, s.month_bucket, s.width AS sw, s.height AS sh
        FROM unlabeled_pin_candidates u
        JOIN screenshots s USING(screenshot_id)
        WHERE u.centroid_x IS NOT NULL AND u.centroid_y IS NOT NULL
        """
    ).fetchall()

    grid = args.grid_px
    buckets = defaultdict(list)
    for row in rows:
        candidate_id, sid, ctype, cx, cy, bw, bh, confidence, ts, month, sw, sh = row
        if not sw or not sh:
            continue
        gx = (cx // grid) * grid
        gy = (cy // grid) * grid
        key = (sw, sh, ctype, gx, gy)
        buckets[key].append(
            {
                "candidate_id": candidate_id,
                "sid": sid,
                "ts": ts,
                "month": month,
                "bw": bw,
                "bh": bh,
                "conf": confidence,
            }
        )

    aircraft_idx = defaultdict(list)
    for sid, registration in conn.execute(
        """SELECT screenshot_id, registration FROM aircraft_observations
           WHERE registration IS NOT NULL"""
    ):
        aircraft_idx[sid].append(registration)

    total_by_dims = Counter()
    for width, height, count in conn.execute(
        "SELECT width, height, COUNT(*) FROM screenshots GROUP BY width, height"
    ):
        total_by_dims[(width, height)] = count

    clusters = []
    rejected_chrome = 0
    rejected_outside_map = 0
    for (sw, sh, ctype, gx, gy), entries in buckets.items():
        distinct_sids = {entry["sid"] for entry in entries}
        if len(distinct_sids) < args.min_recur:
            continue
        total_for_dims = total_by_dims.get((sw, sh), 0)
        if total_for_dims:
            recur_pct = 100.0 * len(distinct_sids) / total_for_dims
            if recur_pct > args.max_recur_pct:
                rejected_chrome += 1
                continue
        if sh:
            y_pct = gy / sh
            if y_pct < 0.13 or y_pct > 0.62:
                rejected_outside_map += 1
                continue
        months = Counter(entry["month"] for entry in entries if entry["month"])
        timestamps = sorted(entry["ts"] for entry in entries if entry["ts"])
        confidences = [
            entry["conf"] for entry in entries if entry["conf"] is not None
        ]
        aircraft_seen = Counter()
        for sid in distinct_sids:
            for registration in aircraft_idx.get(sid, []):
                aircraft_seen[registration] += 1
        clusters.append(
            {
                "cluster_key": f"{sw}x{sh}_{ctype}_{gx}_{gy}",
                "image_dims": f"{sw}x{sh}",
                "candidate_type": ctype,
                "grid_x_px": gx,
                "grid_y_px": gy,
                "n_hits": len(entries),
                "n_distinct_screenshots": len(distinct_sids),
                "first_seen": timestamps[0] if timestamps else None,
                "last_seen": timestamps[-1] if timestamps else None,
                "months_active": ",".join(sorted(months)),
                "avg_confidence": (
                    round(sum(confidences) / len(confidences), 2)
                    if confidences
                    else None
                ),
                "top_aircraft": ",".join(
                    f"{registration}({count})"
                    for registration, count in aircraft_seen.most_common(3)
                ),
                "n_unique_aircraft": len(aircraft_seen),
                "identity_state": "CANDIDATE_NOT_IDENTITY",
                "certification_state": "AUDIT_ONLY",
            }
        )

    clusters.sort(key=lambda cluster: -cluster["n_distinct_screenshots"])
    OUTS.mkdir(parents=True, exist_ok=True)
    fields = [
        "cluster_key",
        "image_dims",
        "candidate_type",
        "grid_x_px",
        "grid_y_px",
        "n_hits",
        "n_distinct_screenshots",
        "first_seen",
        "last_seen",
        "months_active",
        "avg_confidence",
        "top_aircraft",
        "n_unique_aircraft",
        "identity_state",
        "certification_state",
    ]
    with (OUTS / "audit_unlabeled_clusters.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(clusters[: args.top_n])

    by_type = Counter(cluster["candidate_type"] for cluster in clusters)
    result = {
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY",
        "identity_state": "CANDIDATE_NOT_IDENTITY",
        "generated_at": _iso_now(),
        "raw_candidates_loaded": len(rows),
        "positional_buckets": len(buckets),
        "recurring_clusters_after_filter": len(clusters),
        "rejected_as_ui_chrome": rejected_chrome,
        "rejected_outside_map_band": rejected_outside_map,
        "emitted_top_n": min(len(clusters), args.top_n),
        "by_candidate_type": dict(by_type.most_common()),
        "output": str((OUTS / "audit_unlabeled_clusters.csv").relative_to(REPO)),
    }
    (OUTS / "audit_unlabeled_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    conn.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
