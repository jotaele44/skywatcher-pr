#!/usr/bin/env python3
"""
OCR Pass 6: Re-run unlabeled-feature detection with FR24-UI masking.

Phase D output was noisy because the original visual detector picked up FR24
UI chrome (status bar, navigation, detail card overlay, aircraft icon
markers) alongside genuine map features. This script:

  1. Masks UI-chrome regions before feature detection
  2. Re-runs OpenCV blob/contour detection with shape filters tuned for
     map-overlay icons (pads, tanks, antennas, road scars)
  3. Replaces unlabeled_pin_candidates rows for re-processed screenshots
     (preserves audit trail via processing_runs row)
  4. Marks every new candidate with detection_method='ui_masked_v2'

REQUIREMENTS (run on user's Mac):
    pip install pillow-heif opencv-python numpy --break-system-packages

UI-chrome mask zones for iPhone-portrait FR24 (1170x2532) — KEEP only the map area:
    status bar:        y_pct < 0.04
    top nav strip:     y_pct < 0.08 - 0.04 ambient overlay
    detail card:       y_pct >= 0.62 (whole bottom card hides map)
    map area to keep:  y_pct ∈ [0.13, 0.60]

The aircraft icon (small triangle/circle ~50px) also pops up wherever the
tapped aircraft is — those are filtered post-detection by clustering: real
features appear at a STABLE pixel position across many screenshots, while
aircraft icons drift with the aircraft.

CLI:
    python3 scripts/rlsm_redetect_unlabeled.py --workers 4
    python3 scripts/rlsm_redetect_unlabeled.py --debug --limit 5  # visualize masks
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

# Map-only zone (keep these pixels, mask everything else)
MAP_ZONE_PCT = (0.0, 0.13, 1.0, 0.60)  # (x_min_pct, y_min_pct, x_max_pct, y_max_pct)


def detect_features_masked(file_path, sw, sh, debug_dir=None, sid=None):
    """Detect candidate visual features in the map-only zone of one screenshot."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
        try: import pillow_heif; pillow_heif.register_heif_opener()
        except ImportError: pass

        img = Image.open(file_path).convert("RGB")
        # Crop map zone
        x0 = int(sw * MAP_ZONE_PCT[0]); y0 = int(sh * MAP_ZONE_PCT[1])
        x1 = int(sw * MAP_ZONE_PCT[2]); y1 = int(sh * MAP_ZONE_PCT[3])
        map_crop = img.crop((x0, y0, x1, y1))
        arr = np.array(map_crop)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        candidates = []

        # 1. Dark-circular blob detection (pads, tanks — typically dark or saturated colors)
        # Adaptive threshold to handle FR24's varying basemap brightness
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 31, 5)
        # Morphological close to consolidate
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        # Find contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 12 or area > 800:  # filter very-small noise & very-large UI
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            ar = w / max(h, 1)
            if ar < 0.3 or ar > 3.5:
                continue
            # Categorize by shape
            perim = cv2.arcLength(cnt, True)
            circularity = 4 * 3.14159 * area / max(perim * perim, 1)
            if circularity > 0.65:
                ctype = "pad"  # round
            elif 0.85 <= ar <= 1.15 and area > 30:
                ctype = "tank"  # squareish
            elif ar > 2.0 or ar < 0.5:
                ctype = "road_scar"
            else:
                ctype = "unknown"
            cx = x + w // 2 + x0
            cy = y + h // 2 + y0
            candidates.append({
                "candidate_type": ctype,
                "centroid_x": cx, "centroid_y": cy,
                "bbox_x": x + x0, "bbox_y": y + y0,
                "bbox_w": w, "bbox_h": h,
                "confidence": min(0.95, circularity + 0.2),
            })

        if debug_dir and sid is not None:
            dbg = arr.copy()
            for c in candidates:
                color = {"pad": (255,0,0), "tank": (0,255,0), "road_scar": (0,0,255)}.get(c["candidate_type"], (200,200,0))
                cv2.rectangle(dbg, (c["bbox_x"]-x0, c["bbox_y"]-y0),
                              (c["bbox_x"]-x0+c["bbox_w"], c["bbox_y"]-y0+c["bbox_h"]), color, 2)
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            Image.fromarray(dbg).save(Path(debug_dir) / f"masked_{sid}.png")
        return candidates, None
    except Exception as e:
        return None, str(e)


def process_one(args):
    sid, file_path, sw, sh, debug_dir = args
    return (sid, *detect_features_masked(file_path, sw, sh, debug_dir, sid))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--debug", action="store_true",
                    help="Save debug images to outputs/_debug_unlabeled/")
    ap.add_argument("--replace", action="store_true",
                    help="Delete existing ui_masked_v2 rows before re-running")
    args = ap.parse_args()

    debug_dir = None
    if args.debug:
        debug_dir = str((REPO / "outputs" / "_debug_unlabeled").resolve())

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Ensure provenance column on unlabeled_pin_candidates
    cols = {r[1] for r in cur.execute("PRAGMA table_info(unlabeled_pin_candidates)")}
    if "detection_method" not in cols:
        cur.execute("ALTER TABLE unlabeled_pin_candidates ADD COLUMN detection_method TEXT")
        conn.commit()
    if args.replace:
        cur.execute("DELETE FROM unlabeled_pin_candidates WHERE detection_method = 'ui_masked_v2'")
        conn.commit()

    rows = cur.execute("""
        SELECT screenshot_id, rel_path, width, height FROM screenshots
        WHERE rel_path IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL
    """).fetchall()
    # Resolve rel_path → absolute path under REPO root
    rows = [(sid, str(REPO / rp), w, h) for (sid, rp, w, h) in rows]
    if args.limit:
        rows = rows[:args.limit]

    cur.execute("""
        INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed)
        VALUES ('redetect_unlabeled_ui_masked_v2', ?, 'in_progress', ?, 0, 0)
    """, (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), len(rows)))
    run_id = cur.lastrowid

    print(f"[redetect] processing {len(rows):,} screenshots with {args.workers} workers")
    work_args = [(r[0], r[1], r[2], r[3], debug_dir) for r in rows]

    n_done = n_fail = n_candidates = 0
    t0 = time.time()

    def handle(results):
        nonlocal n_done, n_fail, n_candidates
        for sid, candidates, err in results:
            n_done += 1
            if err:
                n_fail += 1; continue
            for c in candidates or []:
                cur.execute("""
                    INSERT INTO unlabeled_pin_candidates
                      (screenshot_id, run_id, candidate_type, centroid_x, centroid_y,
                       bbox_x, bbox_y, bbox_w, bbox_h, confidence, detected_at, detection_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ui_masked_v2')
                """, (sid, run_id, c["candidate_type"], c["centroid_x"], c["centroid_y"],
                      c["bbox_x"], c["bbox_y"], c["bbox_w"], c["bbox_h"], c["confidence"],
                      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                n_candidates += 1
            if n_done % 100 == 0:
                conn.commit()
                rate = n_done / max(time.time() - t0, 0.001)
                print(f"  [{n_done}/{len(work_args)}] {rate:.1f}/s, {n_candidates} candidates, {n_fail} failed")

    if args.workers <= 1:
        for w in work_args:
            handle([process_one(w)])
    else:
        batch = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for f in as_completed(ex.submit(process_one, w) for w in work_args):
                batch.append(f.result())
                if len(batch) >= 30:
                    handle(batch); batch = []
            if batch:
                handle(batch)
    conn.commit()
    cur.execute("""UPDATE processing_runs SET ended_at=?, status='completed',
                   n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), n_done, n_fail,
                 json.dumps({"candidates_emitted": n_candidates}), run_id))
    conn.commit()
    conn.close()
    print(json.dumps({
        "screenshots_processed": n_done,
        "failed": n_fail,
        "candidates_emitted": n_candidates,
        "elapsed_minutes": round((time.time() - t0) / 60, 1),
        "next_steps": "Re-run scripts/rlsm_cluster_unlabeled_pois.py to surface "
                       "clusters from the cleaner candidates, then "
                       "scripts/rlsm_geocode_unlabeled.py to map them.",
    }, indent=2))


if __name__ == "__main__":
    main()
