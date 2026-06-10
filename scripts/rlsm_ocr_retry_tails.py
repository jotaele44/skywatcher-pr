#!/usr/bin/env python3
"""
OCR Pass 3b: Re-OCR aircraft_card with stronger preprocessing.

For aircraft_observations STILL unresolved after rlsm_recover_tails_textmine.py,
re-OCR the aircraft_card zone with:
  - 2x upscale (Lanczos)
  - OTSU binarization (high contrast for white-on-dark FR24 text)
  - Tesseract --psm 7 (single-line) and --psm 8 (single-word) modes
  - Restricted character whitelist for registration zone

REQUIREMENTS (run on user's Mac):
    pip install pytesseract pillow-heif opencv-python --break-system-packages
    brew install tesseract

CLI:
    python3 scripts/rlsm_ocr_retry_tails.py             # process all unresolved
    python3 scripts/rlsm_ocr_retry_tails.py --workers 4 # parallel
    python3 scripts/rlsm_ocr_retry_tails.py --limit 50  # quick test
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"

# Aircraft_card zone is 65–95% of image height (per fr24/rlsm_zones.py)
CARD_ZONE = (0.65, 0.95)

REG_PAT = re.compile(r"REG\.?\s*([A-Z0-9][A-Z0-9\-]{1,6})", re.IGNORECASE)


def ocr_card_robust(file_path: str, sw: int, sh: int) -> str:
    """Re-OCR aircraft_card with stronger preprocessing. Returns combined text."""
    from PIL import Image
    try: import pillow_heif; pillow_heif.register_heif_opener()
    except ImportError: pass
    import pytesseract
    import numpy as np
    try: import cv2
    except ImportError: cv2 = None

    img = Image.open(file_path).convert("RGB")
    y0 = int(sh * CARD_ZONE[0])
    y1 = int(sh * CARD_ZONE[1])
    crop = img.crop((0, y0, sw, y1))

    # Variant A: 2x upscale + binarization
    crop_2x = crop.resize((crop.size[0]*2, crop.size[1]*2), Image.LANCZOS)
    texts = []

    # Path 1: PIL grayscale + threshold
    gray = crop_2x.convert("L")
    if cv2 is not None:
        arr = np.array(gray)
        # OTSU threshold
        _, otsu = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = Image.fromarray(otsu)
        # Both polarities (FR24 has white text on dark)
        inverted = Image.fromarray(255 - otsu)
        for variant_img in [binary, inverted, gray]:
            for psm in [6, 7, 11]:
                cfg = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789. /-"
                try:
                    t = pytesseract.image_to_string(variant_img, config=cfg)
                    if t.strip():
                        texts.append(t)
                except Exception:
                    pass
    else:
        for psm in [6, 11]:
            try:
                t = pytesseract.image_to_string(gray, config=f"--psm {psm}")
                if t.strip(): texts.append(t)
            except Exception:
                pass

    return " | ".join(texts)


def ocr_one(args):
    obs_id, sid, file_path, sw, sh = args
    try:
        text = ocr_card_robust(file_path, sw, sh)
        matches = REG_PAT.findall(text)
        candidates = []
        for m in matches:
            up = m.upper().replace("-", "").replace(" ", "")
            if up in ("NA", "N/A", "NONE"): continue
            if not up.startswith("N"): continue
            if 3 <= len(up) <= 7:
                candidates.append(up)
        return obs_id, sid, text, candidates, None
    except Exception as e:
        return obs_id, sid, None, [], str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # Load FAA tails for variant matching
    faa_set = set()
    if FAA_CSV.exists():
        for r in csv.DictReader(FAA_CSV.open()):
            t = (r.get("registration") or "").upper().strip()
            if t: faa_set.add(t)

    # Reuse OCR_SUBS variant generator from the textmine script
    sys.path.insert(0, str(REPO / "scripts"))
    from rlsm_recover_tails_textmine import gen_ocr_variants, TAIL_PAT

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Ensure provenance column
    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    if "registration_provenance" not in cols:
        cur.execute("ALTER TABLE aircraft_observations ADD COLUMN registration_provenance TEXT")
        conn.commit()

    rows = cur.execute("""
        SELECT a.aircraft_obs_id, a.screenshot_id, s.rel_path, s.width, s.height
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NULL AND s.rel_path IS NOT NULL
    """).fetchall()
    # Resolve rel_path → absolute path under REPO root
    rows = [(oid, sid, str(REPO / rp), w, h) for (oid, sid, rp, w, h) in rows]
    if args.limit:
        rows = rows[:args.limit]
    print(f"[retry-OCR] processing {len(rows):,} unresolved observations with {args.workers} workers")

    cur.execute("""
        INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed)
        VALUES ('ocr_retry_tails', ?, 'in_progress', ?, 0, 0)
    """, (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), len(rows)))
    run_id = cur.lastrowid

    n_done = n_fail = n_recovered = 0
    t0 = time.time()
    recovered = []

    def handle(results):
        nonlocal n_done, n_fail, n_recovered
        for obs_id, sid, text, candidates, err in results:
            n_done += 1
            if err:
                n_fail += 1
                continue
            best = None
            for cand in candidates:
                if cand in faa_set:
                    best = cand; break
                variants = gen_ocr_variants(cand, max_subs=3)
                hits = {v for v in variants if v in faa_set and TAIL_PAT.match(v)}
                if len(hits) == 1:
                    best = next(iter(hits)); break
            if best:
                n_recovered += 1
                recovered.append((obs_id, sid, ",".join(candidates), best))
                cur.execute("""
                    UPDATE aircraft_observations
                    SET registration = ?, registration_provenance = 'ocr_retry_strong_preproc'
                    WHERE aircraft_obs_id = ?
                """, (best, obs_id))
            if n_done % 100 == 0:
                conn.commit()
                rate = n_done / max(time.time() - t0, 0.001)
                eta = (len(rows) - n_done) / max(rate, 0.001) / 60
                print(f"  [{n_done}/{len(rows)}] {rate:.1f}/s, {n_recovered} recovered, ETA {eta:.1f}min")

    if args.workers <= 1:
        for r in rows:
            handle([ocr_one(r)])
    else:
        batch = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for f in as_completed(ex.submit(ocr_one, r) for r in rows):
                batch.append(f.result())
                if len(batch) >= 40:
                    handle(batch); batch = []
            if batch:
                handle(batch)

    conn.commit()
    cur.execute("""UPDATE processing_runs SET ended_at=?, status='completed',
                   n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 n_done, n_fail, json.dumps({"recovered": n_recovered}), run_id))
    conn.commit()
    conn.close()

    OUTS = REPO / "outputs"
    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_tail_recovery_ocr_retry.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["obs_id","screenshot_id","ocr_candidates","recovered_tail"])
        for r in recovered:
            w.writerow(r)

    print(json.dumps({
        "obs_processed": n_done,
        "obs_failed": n_fail,
        "tails_recovered": n_recovered,
        "elapsed_minutes": round((time.time() - t0) / 60, 1),
        "outputs": ["outputs/intel_tail_recovery_ocr_retry.csv"],
    }, indent=2))


if __name__ == "__main__":
    main()
