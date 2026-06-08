"""
RLSM flight-track features — Phase 7 extractor (B-flight-track).

Populates the previously-empty `flight_track_features` table with a per-
screenshot path-shape classification. This implementation is a **heuristic
intermediate**: it derives `path_shape`, `has_hover`, and `confidence` from
already-extracted `aircraft_observations` (`speed_kt`, `heading_deg`,
`identity_status`), NOT from pixel-level connected-component analysis of the
on-screen track marker.

Honest limits
-------------
- No pixel analysis → `track_length_px` and `bbox_*` columns stay NULL.
- `has_loop` / `has_orbit` / `has_gap` cannot be derived without the actual
  track pixels and are left at 0 (their meaning is "did we see one?", and the
  answer here is "we couldn't look"). The full CV-based classifier remains
  a deferred follow-up — see docs/NEXT_100_TASKS.md "B-flight-track".
- `follows_coast` / `near_airport` are spatial-context fields the heuristic
  doesn't compute; left at 0.

What this does ship
-------------------
- `path_shape` from aircraft-observation signals:
    'hover'  — at least one aircraft_observation with speed_kt = 0 in this screenshot
    'linear' — at least one aircraft_observation with speed_kt > 0 AND heading_deg set
    'multi'  — multiple aircraft_observations with different headings (>= 30°
                 apart) on the same screenshot — implies multiple aircraft or
                 a quick turn
    'absent' — no aircraft_observation rows for this screenshot
- `has_hover` = 1 iff any speed_kt = 0 observation
- `confidence` = 0.3 (LOW on the canonical [0,1] scale) — honest signal that
   this is a heuristic, not a measurement.

Idempotency
-----------
The runner inserts only when no `flight_track_features` row exists for a
screenshot. Re-running is a no-op for already-classified screenshots; new
screenshots get classified. To force re-classification, delete the row(s)
first.

CLI
---
    python3 -m fr24.rlsm_flight_track [--limit N] [--budget-sec S]

Defaults: no limit, 35-second budget.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

# Per-classification confidence: LOW on the canonical [0,1] scale — see
# docs/SCHEMA_AND_EXPORT_CONTRACTS.md confidence-scale policy.
HEURISTIC_CONFIDENCE = 0.3

# Heading delta (degrees) above which we consider two observations to indicate
# multiple-aircraft / quick-turn — i.e., path_shape='multi'.
MULTI_HEADING_DELTA_DEG = 30


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _classify_screenshot(observations: list) -> tuple:
    """Classify a single screenshot's path_shape from its aircraft_observations rows.

    *observations* is a list of (speed_kt, heading_deg) tuples — None values
    are treated as "unknown" (do not contribute to classification).

    Returns (path_shape, has_hover_int). The full row dict is assembled by the
    caller — this function isolates the heuristic so it can be unit-tested
    independently of the SQLite layer.
    """
    if not observations:
        return ("absent", 0)

    has_hover = any(speed == 0 for speed, _ in observations if speed is not None)
    if has_hover:
        return ("hover", 1)

    # 'multi' = at least two observations with headings differing by >= threshold.
    headings = sorted({h for _, h in observations if h is not None})
    for i, h1 in enumerate(headings):
        for h2 in headings[i + 1:]:
            delta = min(abs(h2 - h1), 360 - abs(h2 - h1))
            if delta >= MULTI_HEADING_DELTA_DEG:
                return ("multi", 0)

    # 'linear' if at least one observation has both speed > 0 AND heading set.
    has_linear_signal = any(
        speed is not None and speed > 0 and heading is not None
        for speed, heading in observations
    )
    if has_linear_signal:
        return ("linear", 0)

    # Aircraft were observed but no speed/heading signal — leave undefined.
    return ("absent", 0)


def run(budget_sec: float = 35.0, limit: int = 0) -> dict:
    """Classify path_shape for every 'ok' screenshot not yet in flight_track_features.

    Returns a snapshot dict identical in shape to the other rlsm runners
    (run_id, targets, processed, failed, elapsed_sec, classifications).
    """
    if not DB.exists():
        raise SystemExit(f"RLSM DB not found: {DB}")
    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('flight_track', ?, 'in_progress', 0, 0, 0)",
        (_iso_now(),),
    )
    run_id = cur.lastrowid
    conn.commit()

    sql = ("SELECT s.screenshot_id FROM screenshots s "
           "WHERE s.ingest_status='ok' "
           "  AND NOT EXISTS (SELECT 1 FROM flight_track_features t WHERE t.screenshot_id = s.screenshot_id) "
           "ORDER BY s.screenshot_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = [row[0] for row in conn.execute(sql).fetchall()]
    n_targets = len(targets)

    start = time.time()
    n_processed = 0
    classifications: dict = {}

    for sid in targets:
        if time.time() - start > budget_sec:
            break
        obs_rows = conn.execute(
            "SELECT speed_kt, heading_deg FROM aircraft_observations WHERE screenshot_id = ?",
            (sid,),
        ).fetchall()
        path_shape, has_hover = _classify_screenshot(obs_rows)
        conn.execute(
            "INSERT INTO flight_track_features "
            "(screenshot_id, run_id, path_shape, has_loop, has_orbit, has_hover, "
            " has_gap, follows_coast, near_airport, confidence, observed_at) "
            "VALUES (?, ?, ?, 0, 0, ?, 0, 0, 0, ?, ?)",
            (sid, run_id, path_shape, has_hover, HEURISTIC_CONFIDENCE, _iso_now()),
        )
        conn.commit()
        n_processed += 1
        classifications[path_shape] = classifications.get(path_shape, 0) + 1

    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?, n_processed=?, "
        "notes=? WHERE run_id=?",
        (_iso_now(), n_targets, n_processed, json.dumps(classifications), run_id),
    )
    conn.commit()
    snapshot = {
        "run_id": run_id,
        "targets": n_targets,
        "processed": n_processed,
        "failed": 0,
        "classifications": classifications,
        "elapsed_sec": round(time.time() - start, 2),
    }
    conn.close()
    return snapshot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--budget-sec", type=float, default=35.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    out = run(args.budget_sec, args.limit)
    print(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
