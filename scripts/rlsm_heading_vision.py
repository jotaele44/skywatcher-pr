#!/usr/bin/env python3
"""
OCR Pass 4: Recover compass heading via vision (NOT OCR).

FR24's iPhone aircraft card renders heading as a rotated arrow icon, not
text — Tesseract can never read it. This script:

  1. Crops the compass-arrow region from the aircraft_card zone
  2. Detects the arrow's rotation angle using OpenCV (PCA on the
     dark/colored pixels of the arrow)
  3. Converts angle to compass bearing (0=N, 90=E, 180=S, 270=W)
  4. Populates aircraft_observations.heading_deg_vision

REQUIREMENTS (run on user's Mac):
    pip install pillow-heif opencv-python numpy --break-system-packages

The compass region varies slightly with FR24 UI version. On iPhone-portrait
1170x2532 FR24 aircraft cards, the heading-arrow icon typically sits at
approximately:
    x: 28% – 38% of width
    y: within the aircraft_card zone (65–95% of total height),
       specifically 70% – 78% of total height

These constants are CALIBRATED FROM ONE SAMPLE. If accuracy is poor,
visualize a sample with --debug to recalibrate.

CLI:
    python3 scripts/rlsm_heading_vision.py --workers 4
    python3 scripts/rlsm_heading_vision.py --debug --limit 20  # save annotated crops
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

# Approximate compass-arrow ROI in iPhone-portrait FR24 (1170x2532)
COMPASS_ROI_PCT = (0.28, 0.70, 0.38, 0.78)  # (x_min, y_min, x_max, y_max) as % of image dims


def detect_arrow_angle(crop_array):
    """Detect the dominant arrow direction in a crop using PCA on dark/colored pixels.
    Returns angle in degrees (0=N=up, 90=E=right) or None if no clear direction."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    if crop_array.size == 0: return None
    # Convert to grayscale and threshold
    if len(crop_array.shape) == 3:
        gray = cv2.cvtColor(crop_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = crop_array
    # FR24 compass arrow is light-on-dark or colored-on-dark
    _, mask = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
    pixels = np.column_stack(np.where(mask > 0))
    if len(pixels) < 30:
        return None
    # PCA
    mean = pixels.mean(axis=0)
    centered = pixels - mean
    cov = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Principal axis = eigenvector with largest eigenvalue
    principal = eigenvectors[:, -1]
    dy, dx = principal[0], principal[1]
    # Determine arrow direction (centroid of upper half vs lower half along principal axis)
    proj = centered @ principal
    upper_count = (proj > 0).sum()
    lower_count = (proj < 0).sum()
    if upper_count < lower_count:
        dy, dx = -dy, -dx
    # Convert to compass bearing: 0=North (up), 90=East (right)
    # In image coords, y axis points DOWN, so North = -dy
    angle_rad = math.atan2(dx, -dy)
    angle_deg = math.degrees(angle_rad) % 360
    return round(angle_deg, 1)


def process_one(args):
    obs_id, sid, file_path, sw, sh, debug, debug_dir = args
    try:
        from PIL import Image
        try: import pillow_heif; pillow_heif.register_heif_opener()
        except ImportError: pass
        import numpy as np
        x0 = int(sw * COMPASS_ROI_PCT[0])
        y0 = int(sh * COMPASS_ROI_PCT[1])
        x1 = int(sw * COMPASS_ROI_PCT[2])
        y1 = int(sh * COMPASS_ROI_PCT[3])
        img = Image.open(file_path).convert("RGB")
        crop = img.crop((x0, y0, x1, y1))
        arr = np.array(crop)
        angle = detect_arrow_angle(arr)
        if debug and debug_dir and angle is not None:
            from PIL import ImageDraw
            dbg = crop.copy()
            d = ImageDraw.Draw(dbg)
            d.text((4, 4), f"H={angle}°", fill="red")
            dbg.save(Path(debug_dir) / f"compass_{obs_id}_{int(angle)}.png")
        return obs_id, angle, None
    except Exception as e:
        return obs_id, None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--debug", action="store_true",
                    help="Save annotated crops to outputs/_debug_compass/ for calibration check")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    if "heading_deg_vision" not in cols:
        cur.execute("ALTER TABLE aircraft_observations ADD COLUMN heading_deg_vision REAL")
        conn.commit()

    rows = cur.execute("""
        SELECT a.aircraft_obs_id, a.screenshot_id, s.rel_path, s.width, s.height
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE s.rel_path IS NOT NULL
          AND a.heading_deg_vision IS NULL
    """).fetchall()
    # Resolve rel_path → absolute path under REPO root
    rows = [(oid, sid, str(REPO / rp), w, h) for (oid, sid, rp, w, h) in rows]
    if args.limit:
        rows = rows[:args.limit]

    debug_dir = None
    if args.debug:
        debug_dir = OUTS / "_debug_compass"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_dir = str(debug_dir)

    print(f"[heading-vision] processing {len(rows):,} observations with {args.workers} workers")
    work_args = [(r[0], r[1], r[2], r[3], r[4], args.debug, debug_dir) for r in rows]

    n_done = n_with_angle = n_fail = 0
    t0 = time.time()

    def handle(results):
        nonlocal n_done, n_with_angle, n_fail
        for obs_id, angle, err in results:
            n_done += 1
            if err:
                n_fail += 1; continue
            if angle is not None:
                n_with_angle += 1
                cur.execute("UPDATE aircraft_observations SET heading_deg_vision=? WHERE aircraft_obs_id=?",
                            (angle, obs_id))
            if n_done % 200 == 0:
                conn.commit()
                rate = n_done / max(time.time() - t0, 0.001)
                print(f"  [{n_done}/{len(work_args)}] {rate:.1f}/s, {n_with_angle} with angle, {n_fail} failed")

    if args.workers <= 1:
        for w in work_args:
            handle([process_one(w)])
    else:
        batch = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for f in as_completed(ex.submit(process_one, w) for w in work_args):
                batch.append(f.result())
                if len(batch) >= 50:
                    handle(batch); batch = []
            if batch:
                handle(batch)
    conn.commit()
    conn.close()
    print(json.dumps({
        "processed":    n_done,
        "with_angle":   n_with_angle,
        "failed":       n_fail,
        "elapsed_minutes": round((time.time() - t0) / 60, 1),
        "calibration_note": "If angles look wrong, re-run with --debug --limit 20 and inspect "
                             "outputs/_debug_compass/ — recalibrate COMPASS_ROI_PCT in this script.",
    }, indent=2))


if __name__ == "__main__":
    main()
