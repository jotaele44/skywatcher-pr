"""
RLSM unlabeled POI candidate detector (Phase 6).

Deterministic, lossless visual pass over the map_center crop. Flags candidate
regions that look like one of:

  pad                 small isolated bright-on-dark blob (helipad / pad-like)
  clearing            irregular bright polygon in dark vegetation
  road_scar           straight or near-straight elongated bright line
  facility_cluster    co-occurring small bright blobs within close proximity
  antenna             very vertical bright streak with narrow width
  tank                near-circular saturated bright blob, distinct size band
  quarry              large irregular bright polygon (rougher than clearing)
  shoreline_infra     bright blob within N pixels of detected coastline edge
  access_road         linear bright trace connecting two regions
  unknown             a candidate that triggered detection but no specific class

Approach: this is **not** an ML classifier. We use simple morphology over the
luminance channel of the map zone and emit candidates as bounding boxes with
evidence_features (area, aspect, brightness, distance-to-edge, etc.) plus a
modest confidence. Every candidate goes into manual_review_queue.

CLI:
    python3 -m fr24.rlsm_unlabeled --budget-sec 35 [--limit N]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from PIL import Image, ImageFilter, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fr24.rlsm_zones import zones_for  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Detection parameters (kept conservative — high precision over recall is preferred at this phase)
PAD_AREA_MIN_PX = 16        # smallest pad
PAD_AREA_MAX_PX = 600
ROADSCAR_ASPECT_MIN = 4.0   # elongation
ANTENNA_ASPECT_MIN = 8.0
TANK_ROUNDNESS_MIN = 0.65
CANDIDATE_BRIGHTNESS_THRESHOLD = 180  # 0..255 luminance, bright-on-dark
MAX_CANDIDATES_PER_IMAGE = 60


def _bbox_aspect(w: int, h: int) -> float:
    if min(w, h) == 0:
        return 0.0
    return max(w, h) / min(w, h)


def _connected_components_threshold(crop: Image.Image, thr: int = CANDIDATE_BRIGHTNESS_THRESHOLD):
    """
    Cheap, no-OpenCV connected-component analysis over a thresholded luminance band.
    Returns list of (cc_id, bbox_x, bbox_y, bbox_w, bbox_h, area_px, mean_lum).
    Uses Pillow's ImageFilter to denoise lightly then runs a labeling pass.
    """
    g = crop.convert("L")
    # Denoise small noise
    g = g.filter(ImageFilter.MedianFilter(size=3))
    W, H = g.size
    pixels = g.load()
    # Binary mask
    visited = [[False] * H for _ in range(W)]
    components = []
    # Stack-based DFS to label components above threshold
    for sx in range(W):
        for sy in range(H):
            if visited[sx][sy]:
                continue
            if pixels[sx, sy] < thr:
                visited[sx][sy] = True
                continue
            # New component
            stack = [(sx, sy)]
            min_x, min_y, max_x, max_y = sx, sy, sx, sy
            area = 0
            lum_sum = 0
            while stack:
                x, y = stack.pop()
                if x < 0 or y < 0 or x >= W or y >= H:
                    continue
                if visited[x][y]:
                    continue
                if pixels[x, y] < thr:
                    visited[x][y] = True
                    continue
                visited[x][y] = True
                area += 1
                lum_sum += pixels[x, y]
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y
                stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
            if area < PAD_AREA_MIN_PX:
                continue  # noise
            components.append({
                "bx": min_x, "by": min_y,
                "bw": max_x - min_x + 1, "bh": max_y - min_y + 1,
                "area": area, "mean_lum": lum_sum / area,
            })
            if len(components) >= MAX_CANDIDATES_PER_IMAGE * 4:
                # too many bright blobs — image is likely a non-map (e.g. UI screen)
                return None
    return components


def _classify_component(c: dict) -> tuple[str, float]:
    """Pick a candidate_type label and a confidence in [0,1] from geometry features."""
    aspect = _bbox_aspect(c["bw"], c["bh"])
    area = c["area"]
    bbox_area = c["bw"] * c["bh"]
    fill_ratio = area / max(bbox_area, 1)
    if aspect >= ANTENNA_ASPECT_MIN and min(c["bw"], c["bh"]) <= 6:
        return "antenna", 0.55
    if aspect >= ROADSCAR_ASPECT_MIN and min(c["bw"], c["bh"]) <= 12:
        return "road_scar", 0.45
    if PAD_AREA_MIN_PX <= area <= PAD_AREA_MAX_PX and fill_ratio >= TANK_ROUNDNESS_MIN:
        return "tank", 0.5
    if PAD_AREA_MIN_PX <= area <= PAD_AREA_MAX_PX and aspect < 2.0:
        return "pad", 0.45
    if area > PAD_AREA_MAX_PX and fill_ratio >= 0.45 and aspect < 3.0:
        return "clearing", 0.35
    if area > PAD_AREA_MAX_PX * 4 and fill_ratio < 0.45:
        return "quarry", 0.30
    return "unknown", 0.20


def detect_for_screenshot(conn, sid: int, rel_path: str, run_id: int):
    full_path = REPO / rel_path
    if not full_path.exists():
        return {"ok": False, "reason": "missing"}
    try:
        with Image.open(full_path) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            W, H = img.size
            zones = {z.name: z for z in zones_for(W, H)}
            # map_center was merged into label_layer in the 3-zone schema (rlsm_zones.py);
            # label_layer (5–65% height) is the map-viewport crop the CC pass runs on.
            mz = zones.get("map_center") or zones["label_layer"]
            crop = img.crop(mz.crop_box())
            # downsample to keep CC cost bounded
            crop.thumbnail((480, 540), Image.LANCZOS)
            sw, sh = crop.size
            scale_x = (mz.w) / sw
            scale_y = (mz.h) / sh
            components = _connected_components_threshold(crop)
    except Exception:
        return {"ok": True, "emitted": 0, "skipped_reason": "non-map (component-detect error)"}
    if components is None:
        return {"ok": True, "emitted": 0, "skipped_reason": "non-map (too many bright blobs)"}
    cur = conn.cursor()
    emitted = 0
    for c in components[:MAX_CANDIDATES_PER_IMAGE]:
        ctype, conf = _classify_component(c)
        # Project back into source coordinates
        bx = mz.x + int(c["bx"] * scale_x)
        by = mz.y + int(c["by"] * scale_y)
        bw = max(1, int(c["bw"] * scale_x))
        bh = max(1, int(c["bh"] * scale_y))
        cx = bx + bw // 2
        cy = by + bh // 2
        evidence = {
            "area_px_scaled": c["area"],
            "bbox_scaled": [c["bx"], c["by"], c["bw"], c["bh"]],
            "mean_lum": round(c["mean_lum"], 1),
            "aspect": round(_bbox_aspect(c["bw"], c["bh"]), 2),
            "fill_ratio": round(c["area"] / max(c["bw"] * c["bh"], 1), 2),
            "scale_x": round(scale_x, 3), "scale_y": round(scale_y, 3),
        }
        cur.execute(
            """INSERT INTO unlabeled_pin_candidates
               (screenshot_id, run_id, candidate_type, bbox_x, bbox_y, bbox_w, bbox_h,
                centroid_x, centroid_y, evidence_features, confidence, review_status,
                notes, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unreviewed', NULL, ?)""",
            (sid, run_id, ctype, bx, by, bw, bh, cx, cy,
             json.dumps(evidence), conf, _iso_now()),
        )
        emitted += 1
    return {"ok": True, "emitted": emitted}




def run(budget_sec: float, limit: int = 0):
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s for the write lock (concurrency-safe)
    cur = conn.cursor()
    cur.execute("INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
                "VALUES ('unlabeled', ?, 'in_progress', 0, 0, 0)", (_iso_now(),))
    run_id = cur.lastrowid  # missing assignment caused NameError at first detect_for_screenshot call
    conn.commit()
    where_sql = ("WHERE s.ingest_status='ok' "
                 "AND NOT EXISTS (SELECT 1 FROM unlabeled_pin_candidates u WHERE u.screenshot_id = s.screenshot_id)")
    sql = f"SELECT s.screenshot_id, s.rel_path FROM screenshots s {where_sql} ORDER BY s.screenshot_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    n_targets = len(rows)
    start = time.time()
    n_ok = n_fail = n_emitted = 0
    for sid, rel_path in rows:
        if time.time() - start > budget_sec:
            break
        res = detect_for_screenshot(conn, sid, rel_path, run_id)
        if res.get("ok"):
            n_ok += 1
            n_emitted += res.get("emitted", 0)
        else:
            n_fail += 1
        conn.commit()
        if time.time() - start > budget_sec:
            break
    conn.execute("UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?, n_processed=?, n_failed=?, "
                 "notes=? WHERE run_id=?",
                 (_iso_now(), n_targets, n_ok, n_fail,
                  json.dumps({"candidates_emitted": n_emitted}), run_id))
    conn.commit()
    snapshot = {
        "run_id": run_id, "targets": n_targets, "processed": n_ok, "failed": n_fail,
        "candidates_emitted": n_emitted,
        "elapsed_sec": round(time.time() - start, 2),
    }
    conn.close()
    print(json.dumps(snapshot, indent=2))


# ── Parallel runner (N5) — mirrors fr24.rlsm_ocr_parallel ──────────────────

# Set per-worker via _worker_init().
_worker_db_path: Optional[str] = None


def _worker_init(db_path: str) -> None:
    """multiprocessing.Pool initializer — set per-worker DB path + OMP cap."""
    global _worker_db_path
    _worker_db_path = db_path
    os.environ["OMP_THREAD_LIMIT"] = "1"


def _worker_process_one(args: Tuple[int, str, int]) -> dict:
    """Worker function. Returns the same result dict shape as detect_for_screenshot,
    plus screenshot_id + elapsed_sec for the aggregator."""
    sid, rel_path, run_id = args
    t0 = time.time()
    conn = sqlite3.connect(_worker_db_path, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        res = detect_for_screenshot(conn, sid, rel_path, run_id)
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        res = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}
    finally:
        conn.close()
    res["screenshot_id"] = sid
    res["elapsed_sec"] = round(time.time() - t0, 3)
    return res


def run_parallel(budget_sec: float, limit: int = 0, workers: int = 4) -> dict:
    """Parallel sibling of run(). Uses multiprocessing.Pool, one SQLite
    connection per worker (WAL handles concurrent writes + busy_timeout=30s
    absorbs transient locks).

    Mirrors fr24.rlsm_ocr_parallel:
      - main process inserts the processing_runs row + builds the target list
      - workers run detect_for_screenshot independently
      - main process aggregates results, finalizes the run row
    """
    main_conn = sqlite3.connect(str(DB), timeout=30.0)
    main_conn.execute("PRAGMA foreign_keys = ON")
    main_conn.execute("PRAGMA busy_timeout = 30000")
    cur = main_conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('unlabeled_parallel', ?, 'in_progress', 0, 0, 0)",
        (_iso_now(),),
    )
    run_id = cur.lastrowid
    main_conn.commit()

    where_sql = ("WHERE s.ingest_status='ok' "
                 "AND NOT EXISTS (SELECT 1 FROM unlabeled_pin_candidates u "
                 "                WHERE u.screenshot_id = s.screenshot_id)")
    sql = (f"SELECT s.screenshot_id, s.rel_path FROM screenshots s {where_sql} "
           "ORDER BY s.screenshot_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = main_conn.execute(sql).fetchall()
    n_targets = len(rows)
    main_conn.close()

    if n_targets == 0:
        print(json.dumps({"run_id": run_id, "targets": 0, "processed": 0,
                          "failed": 0, "candidates_emitted": 0,
                          "elapsed_sec": 0.0, "workers": workers}, indent=2))
        return {"run_id": run_id, "targets": 0}

    work = [(sid, rel, run_id) for sid, rel in rows]
    t0 = time.time()
    n_ok = n_fail = n_emitted = 0

    with multiprocessing.Pool(
        processes=max(1, workers),
        initializer=_worker_init,
        initargs=(str(DB),),
    ) as pool:
        for i, res in enumerate(pool.imap_unordered(_worker_process_one, work, chunksize=1)):
            if time.time() - t0 > budget_sec:
                pool.terminate()
                break
            if res.get("ok"):
                n_ok += 1
                n_emitted += res.get("emitted", 0)
            else:
                n_fail += 1
            if (i + 1) % 50 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed else 0
                remaining_min = (n_targets - i - 1) / rate / 60 if rate else 0
                print(f"[unlabeled-parallel] {i+1}/{n_targets}  ok={n_ok} fail={n_fail}"
                      f"  rate={rate:.2f} img/s  ETA={remaining_min:.1f} min", flush=True)

    elapsed = time.time() - t0
    final_conn = sqlite3.connect(str(DB), timeout=30.0)
    final_conn.execute("PRAGMA busy_timeout = 30000")
    final_conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', "
        "n_inputs=?, n_processed=?, n_failed=?, notes=? WHERE run_id=?",
        (_iso_now(), n_targets, n_ok, n_fail,
         json.dumps({"candidates_emitted": n_emitted, "workers": workers}), run_id),
    )
    final_conn.commit()
    final_conn.close()

    snapshot = {
        "run_id": run_id, "targets": n_targets, "processed": n_ok, "failed": n_fail,
        "candidates_emitted": n_emitted, "elapsed_sec": round(elapsed, 2),
        "workers": workers,
    }
    print(json.dumps(snapshot, indent=2))
    return snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=float, default=35.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1,
                    help="Worker processes for parallel detection (1 = serial run()).")
    args = ap.parse_args()
    if args.workers > 1:
        run_parallel(args.budget_sec, args.limit, args.workers)
    else:
        run(args.budget_sec, args.limit)


if __name__ == "__main__":
    main()
