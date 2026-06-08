"""
RLSM geo-anchor populator — Phase 8 extractor (B-geo-anchors).

Populates the previously-empty `geo_anchors` table with `anchor_kind='static'`
rows derived from `configs/georef_anchors.csv` — a 5-anchor reference set
(SJU, BQN, PSE, SIG airports + PR centroid) with resolution-independent
pixel-fraction coordinates and known lat/lon.

For every `ingest_status='ok'` screenshot, this runner emits ~5 rows mapping
the static anchors into that screenshot's pixel grid (pixel_x = round(
pixel_x_fraction * screenshot.width)). Downstream consumers (e.g. a future
pixel→lat/lon homography fit) can use these 5 known correspondences directly
or fit an affine transform on them.

Honest limits
-------------
This ships **`anchor_kind='static'`** only. The `geo_anchors.anchor_kind`
enum also allows `'derived'` (anchors matched per-screenshot via OCR'd
labeled_pois → registry lookup) and `'failed'` (screenshots where no match
worked). Those branches are the v2 pass and are NOT in this module:

- Static anchors assume the FR24 PR view is consistent across the entire
  baseline (which it is — all screenshots share the same map projection
  and approximate zoom). Per-screenshot pan/zoom drift is NOT modeled.
- Confidence is `STATIC_ANCHOR_CONFIDENCE=0.6` (MEDIUM on the canonical
  [0,1] scale): higher than the heuristic flight-track classifier because
  the anchor positions are known measured constants, but bounded below 1.0
  because the per-screenshot zoom-invariance assumption is unverified.
- A screenshot with NULL `width` is skipped (the pixel-fraction multiply
  would produce a nonsense pixel_x).

Idempotency
-----------
The runner emits zero new rows for any screenshot already in `geo_anchors`.
Re-running is a no-op for processed screenshots; new ones get filled.

CLI
---
    python3 -m fr24.rlsm_geo_anchors [--limit N] [--budget-sec S]

Defaults: no limit, 45-second budget.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
ANCHORS_CSV = REPO / "configs" / "georef_anchors.csv"

# Static anchors are known-good measured points — MEDIUM confidence on the
# canonical [0,1] scale. NOT 1.0 because per-screenshot zoom drift is
# unverified in this intermediate.
STATIC_ANCHOR_CONFIDENCE = 0.6


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_anchor_registry(path: Path = ANCHORS_CSV) -> list[dict]:
    """Load the static anchor registry from CSV.

    Returns a list of dicts with float lat/lon/pixel_x_fraction/pixel_y_fraction.
    """
    if not path.exists():
        raise SystemExit(f"Anchor registry not found: {path}")
    anchors: list[dict] = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            anchors.append({
                "anchor_id_text": row["anchor_id"],
                "name": row["name"],
                "pixel_x_fraction": float(row["pixel_x_fraction"]),
                "pixel_y_fraction": float(row["pixel_y_fraction"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "notes": row.get("notes", ""),
            })
    return anchors


def _project_to_pixels(anchor: dict, width: int, height: int) -> tuple[int, int]:
    """Project a pixel-fraction anchor into a screenshot's pixel grid."""
    return (
        round(anchor["pixel_x_fraction"] * width),
        round(anchor["pixel_y_fraction"] * height),
    )


def run(budget_sec: float = 45.0, limit: int = 0) -> dict:
    """Populate geo_anchors with anchor_kind='static' rows for every 'ok' screenshot.

    Skips screenshots with width=NULL (cannot project) and screenshots already
    in geo_anchors. Returns a snapshot dict matching the shape of the other
    rlsm runners (run_id, targets, processed, failed, elapsed_sec, anchors_inserted).
    """
    if not DB.exists():
        raise SystemExit(f"RLSM DB not found: {DB}")
    anchors = _load_anchor_registry()
    n_anchors_per_screenshot = len(anchors)

    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('geo_anchors', ?, 'in_progress', 0, 0, 0)",
        (_iso_now(),),
    )
    run_id = cur.lastrowid
    conn.commit()

    sql = ("SELECT s.screenshot_id, s.width, s.height FROM screenshots s "
           "WHERE s.ingest_status='ok' "
           "  AND s.width IS NOT NULL AND s.height IS NOT NULL "
           "  AND NOT EXISTS (SELECT 1 FROM geo_anchors g WHERE g.screenshot_id = s.screenshot_id) "
           "ORDER BY s.screenshot_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = conn.execute(sql).fetchall()
    n_targets = len(targets)

    start = time.time()
    n_processed = 0
    n_anchors_inserted = 0

    for sid, width, height in targets:
        if time.time() - start > budget_sec:
            break
        for anchor in anchors:
            px, py = _project_to_pixels(anchor, width, height)
            conn.execute(
                "INSERT INTO geo_anchors "
                "(screenshot_id, anchor_kind, name, pixel_x, pixel_y, lat, lon, "
                " confidence, source, notes, observed_at) "
                "VALUES (?, 'static', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    anchor["name"],
                    px,
                    py,
                    anchor["lat"],
                    anchor["lon"],
                    STATIC_ANCHOR_CONFIDENCE,
                    f"configs/georef_anchors.csv#{anchor['anchor_id_text']}",
                    anchor["notes"] or None,
                    _iso_now(),
                ),
            )
            n_anchors_inserted += 1
        conn.commit()
        n_processed += 1

    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?, n_processed=?, "
        "notes=? WHERE run_id=?",
        (
            _iso_now(),
            n_targets,
            n_processed,
            json.dumps({"anchors_per_screenshot": n_anchors_per_screenshot,
                        "anchors_inserted": n_anchors_inserted}),
            run_id,
        ),
    )
    conn.commit()
    snapshot = {
        "run_id": run_id,
        "targets": n_targets,
        "processed": n_processed,
        "failed": 0,
        "anchors_per_screenshot": n_anchors_per_screenshot,
        "anchors_inserted": n_anchors_inserted,
        "elapsed_sec": round(time.time() - start, 2),
    }
    conn.close()
    return snapshot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--budget-sec", type=float, default=45.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    out = run(args.budget_sec, args.limit)
    print(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
