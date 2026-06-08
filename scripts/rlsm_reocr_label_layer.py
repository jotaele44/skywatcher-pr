#!/usr/bin/env python3
"""
OCR Pass 2-Helper: Re-OCR label_layer with WORD-LEVEL pixel boxes.

The original Phase 3 OCR used Tesseract image_to_string and stored only the
zone-level OCR text. To geocode unlabeled candidates, we need per-word
bounding boxes so we can pin "MAYAGUEZ" to its actual pixel position on
each screenshot, then fit a pixel→lat/lon affine per screenshot.

This script re-runs Tesseract in image_to_data mode (TSV with bounding
boxes) on the label_layer zone of every screenshot, then populates
labeled_pois.centroid_x/centroid_y with the actual word-level pixel
centroid (not the zone-center fallback the original extractor used).

REQUIREMENTS (run on user's Mac):
    pip install pytesseract pillow-heif --break-system-packages
    brew install tesseract

CLI:
    python3 scripts/rlsm_reocr_label_layer.py
    python3 scripts/rlsm_reocr_label_layer.py --workers 4 --limit 100  # quick test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
BASELINE = REPO / "data" / "FR24_baseline"

# Reuse the same vocabulary as the original POI extractor
sys.path.insert(0, str(REPO))
try:
    from fr24.rlsm_extractors import _load_pr_vocab
except ImportError:
    # Fallback: lightweight inline vocab loader using just places.geojson
    import json as _json
    def _load_pr_vocab(places_path, anchors_path):
        vocab = set()
        try:
            gj = _json.load(open(places_path))
            for f in gj.get("features", []):
                name = (f.get("properties", {}).get("NAME") or "").upper().strip()
                if name: vocab.add(name)
        except Exception: pass
        try:
            import csv as _csv
            for r in _csv.DictReader(open(anchors_path)):
                for k in ("anchor_id", "name"):
                    v = (r.get(k) or "").upper().strip()
                    if v: vocab.add(v)
        except Exception: pass
        return vocab


def _ascii_up(s: str) -> str:
    if not s: return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).upper().strip()


def ocr_one_screenshot(args):
    """Worker: re-OCR one screenshot's label_layer with word-level boxes."""
    sid, file_path, sw, sh = args
    try:
        from PIL import Image
        try: import pillow_heif; pillow_heif.register_heif_opener()
        except ImportError: pass
        import pytesseract
        img = Image.open(file_path)
        # Crop to label_layer zone (5% – 65% of height)
        y0 = int(sh * 0.05); y1 = int(sh * 0.65)
        crop = img.crop((0, y0, sw, y1))
        data = pytesseract.image_to_data(crop, output_type=pytesseract.Output.DICT, config='--psm 11')
        # Return word + box (translate back to full-image coords)
        words = []
        for i, w in enumerate(data["text"]):
            w = (w or "").strip()
            if not w or len(w) < 3: continue
            try:
                x = int(data["left"][i]); y = int(data["top"][i]) + y0
                width = int(data["width"][i]); height = int(data["height"][i])
                conf = int(data["conf"][i])
            except (ValueError, KeyError):
                continue
            if conf < 30:  # Tesseract confidence threshold
                continue
            words.append({"text": w, "x": x, "y": y, "w": width, "h": height,
                           "cx": x + width//2, "cy": y + height//2, "conf": conf})
        return sid, words, None
    except Exception as e:
        return sid, None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="Limit screenshots (0=all)")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip screenshots whose POI centroids are already word-level (have multiple distinct centroids)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed)
        VALUES ('reocr_label_layer_word_boxes', ?, 'in_progress', 0, 0, 0)
    """, (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    run_id = cur.lastrowid

    # Skip screenshots that already have per-word centroids (multiple distinct pixels)
    skip_sids = set()
    if args.only_missing:
        for r in cur.execute("""
            SELECT screenshot_id FROM labeled_pois
            WHERE centroid_x IS NOT NULL
            GROUP BY screenshot_id
            HAVING COUNT(DISTINCT centroid_x || ',' || centroid_y) >= 2
        """):
            skip_sids.add(r[0])

    # Load screenshots
    rows = cur.execute("""
        SELECT screenshot_id, rel_path, width, height FROM screenshots
        WHERE rel_path IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL
    """).fetchall()
    # Resolve rel_path → absolute path under REPO root
    rows = [(sid, str(REPO / rp), w, h) for (sid, rp, w, h) in rows]
    rows = [r for r in rows if r[0] not in skip_sids]
    if args.limit:
        rows = rows[:args.limit]
    print(f"[reocr] processing {len(rows):,} screenshots with {args.workers} workers")

    # Vocab for label matching
    vocab = _load_pr_vocab(REPO / "data" / "places.geojson", REPO / "configs" / "georef_anchors.csv")
    vocab_ascii = {_ascii_up(v): v for v in vocab}

    n_done = n_failed = n_updates = 0
    t0 = time.time()

    def process_results(results):
        nonlocal n_done, n_failed, n_updates
        for sid, words, err in results:
            n_done += 1
            if err:
                n_failed += 1
                if n_failed < 5: print(f"  [warn] sid={sid}: {err}")
                continue
            if not words:
                continue
            # For each labeled_poi on this screenshot whose normalized_label matches
            # one of the words (ASCII), update centroid_x/y to the word's pixel centroid
            poi_rows = cur.execute(
                "SELECT poi_id, normalized_label FROM labeled_pois WHERE screenshot_id = ?",
                (sid,)
            ).fetchall()
            # Build a word → centroid lookup (longest match wins)
            words_by_ascii = {}
            for w in words:
                key = _ascii_up(w["text"])
                if key and key not in words_by_ascii:
                    words_by_ascii[key] = (w["cx"], w["cy"])
            for poi_id, label in poi_rows:
                ascii_label = _ascii_up(label)
                # Direct word match
                if ascii_label in words_by_ascii:
                    cx, cy = words_by_ascii[ascii_label]
                    cur.execute("UPDATE labeled_pois SET centroid_x=?, centroid_y=? WHERE poi_id=?",
                                (cx, cy, poi_id))
                    n_updates += 1
                    continue
                # Substring match: any word containing the label as substring
                for wkey, (cx, cy) in words_by_ascii.items():
                    if ascii_label in wkey or wkey in ascii_label:
                        if abs(len(wkey) - len(ascii_label)) <= 3:
                            cur.execute("UPDATE labeled_pois SET centroid_x=?, centroid_y=? WHERE poi_id=?",
                                        (cx, cy, poi_id))
                            n_updates += 1
                            break
            if n_done % 200 == 0:
                conn.commit()
                rate = n_done / max(time.time() - t0, 0.001)
                print(f"  [{n_done}/{len(rows)}] {rate:.1f}/s, {n_failed} fail, {n_updates} POI updates")

    if args.workers <= 1:
        for r in rows:
            process_results([ocr_one_screenshot(r)])
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            batch = []
            for f in as_completed(ex.submit(ocr_one_screenshot, r) for r in rows):
                batch.append(f.result())
                if len(batch) >= 50:
                    process_results(batch); batch = []
            if batch:
                process_results(batch)

    conn.commit()
    cur.execute("""UPDATE processing_runs SET ended_at=?, status='completed',
                   n_inputs=?, n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 len(rows), n_done, n_failed,
                 json.dumps({"poi_updates": n_updates}), run_id))
    conn.commit()
    conn.close()
    print(json.dumps({"screenshots_processed": n_done, "failed": n_failed,
                       "labeled_poi_centroids_updated": n_updates,
                       "elapsed_seconds": round(time.time() - t0, 1)}, indent=2))


if __name__ == "__main__":
    main()
