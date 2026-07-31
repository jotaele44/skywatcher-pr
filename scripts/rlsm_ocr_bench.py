#!/usr/bin/env python3
"""
Measure OCR preprocessing variants on a fixed screenshot sample.

Read-only with respect to the pipeline tables: nothing here writes to
``ocr_observations`` or ``labeled_pins``. Results append to
``outputs/ocr_bench.jsonl`` so a run is resumable and a later invocation can
re-report without redoing the OCR.

This exists so ``ZONE_OCR_CONFIG`` is a measurement rather than a guess. If you
change a zone's ``preprocess`` or ``scale``, re-run this and update the comment
in fr24/rlsm_zones.py with what you actually saw.

Metrics per (screenshot, zone, variant):
    conf_mean   Tesseract mean word confidence
    n_words     words returned above the storage thresholds
    gaz_hits    distinct Tier-1 gazetteer matches — the metric that decides
                whether a frame yields usable POIs, not just more characters

CLI:
    python3 scripts/rlsm_ocr_bench.py --sample 30 --budget-sec 600
    python3 scripts/rlsm_ocr_bench.py --report
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUT = REPO / "outputs" / "ocr_bench.jsonl"

# Tesseract links OpenMP, which deadlocks in forked workers. Every entry point
# in this package sets this; the bench forks too, so it needs it as well.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# (name, preprocess_mode, scale, lang)
VARIANTS = [
    ("baseline",          "none",          1.0, "eng"),
    ("high_contrast",     "high_contrast", 2.0, "eng"),
    ("label_mask_2x",     "label_mask",    2.0, "eng"),
    ("label_mask_3x",     "label_mask",    3.0, "eng"),
    ("high_contrast_spa", "high_contrast", 2.0, "spa+eng"),
]
ZONES = ("label_layer", "aircraft_card")


def available_langs() -> set:
    try:
        import pytesseract
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def _job(task):
    sid, path, variant, zone_name = task
    name, mode, scale, lang = variant
    try:
        from PIL import Image, ImageOps
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass  # HEIC files unsupported if pillow_heif absent
        import pytesseract

        from fr24.rlsm_preprocess import preprocess
        from fr24.rlsm_wordboxes import words_from_tesseract_data
        from fr24.rlsm_zones import ZONE_OCR_CONFIG, zones_for

        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            zones = {z.name: z for z in zones_for(*im.size)}
            if zone_name not in zones:
                return None
            zone = zones[zone_name]
            crop = im.crop(zone.crop_box())
        crop = preprocess(crop, mode, scale)

        psm = ZONE_OCR_CONFIG.get(zone_name, {}).get("psm", 6)
        cfg = f"--oem 1 --psm {psm} -l {lang}"
        t0 = time.time()
        data = pytesseract.image_to_data(crop, config=cfg,
                                         output_type=pytesseract.Output.DICT)
        elapsed = time.time() - t0

        sc = scale if mode != "none" else 1.0
        boxes = words_from_tesseract_data(data, x_off=zone.x, y_off=zone.y, scale=sc)
        confs = [c for c, w in zip(data["conf"], data["text"], strict=True)
                 if w.strip() and c >= 0]

        try:
            from fr24.rlsm_extractors import scan_words_for_pois
            hits = [h["label"] for h in scan_words_for_pois(boxes) if h.get("entry")]
        except Exception:
            hits = []

        return {"screenshot_id": sid, "zone": zone_name, "variant": name,
                "conf_mean": round(sum(confs) / len(confs), 2) if confs else 0.0,
                "n_words": len(boxes), "gaz_hits": len(set(hits)),
                "hits": sorted(set(hits))[:8], "sec": round(elapsed, 2)}
    except Exception as e:
        return {"screenshot_id": sid, "zone": zone_name, "variant": variant[0],
                "error": str(e)[:160]}


def load_done() -> set:
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done.add((r["screenshot_id"], r["zone"], r["variant"]))
            except Exception:
                continue
    return done


def report() -> None:
    if not OUT.exists():
        print("[bench] nothing measured yet")
        return
    rows = [json.loads(line)
            for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]
    agg = defaultdict(list)
    for r in rows:
        if "error" not in r:
            agg[(r["zone"], r["variant"])].append(r)
    for zone in ZONES:
        if not any(z == zone for z, _ in agg):
            continue
        print(f"\n-- {zone} " + "-" * (58 - len(zone)))
        print(f"  {'variant':20} {'n':>4} {'conf':>7} {'words':>7} {'gaz/frame':>11} {'sec':>6}")
        base = None
        for v, *_ in VARIANTS:
            rs = agg.get((zone, v))
            if not rs:
                continue
            conf = sum(r["conf_mean"] for r in rs) / len(rs)
            words = sum(r["n_words"] for r in rs) / len(rs)
            gaz = sum(r["gaz_hits"] for r in rs) / len(rs)
            sec = sum(r["sec"] for r in rs) / len(rs)
            if v == "baseline":
                base = gaz
            delta = "" if base is None or v == "baseline" else f"   ({gaz - base:+.2f})"
            print(f"  {v:20} {len(rs):>4} {conf:>7.1f} {words:>7.1f} {gaz:>11.2f} {sec:>6.2f}{delta}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark OCR preprocessing variants.")
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--budget-sec", type=float, default=600)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return

    langs = available_langs()
    variants = [v for v in VARIANTS if not langs or all(p in langs for p in v[3].split("+"))]
    skipped = [v[0] for v in VARIANTS if v not in variants]
    if skipped:
        print(f"[bench] skipping (missing traineddata): {skipped} available={sorted(langs)}")

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("""SELECT screenshot_id, rel_path FROM screenshots
                           WHERE ingest_status='ok'
                           ORDER BY month_bucket, screenshot_id""").fetchall()
    conn.close()
    rows = [(s, str(REPO / p)) for s, p in rows if (REPO / p).exists()]
    if not rows:
        print("[bench] no screenshots on disk")
        return
    # Even stride across month buckets so one month's map style cannot dominate.
    step = max(1, len(rows) // args.sample)
    sample = rows[::step][:args.sample]

    done = load_done()
    tasks = [(sid, path, v, z) for (sid, path) in sample for v in variants for z in ZONES
             if (sid, z, v[0]) not in done]
    print(f"[bench] sample={len(sample)} variants={len(variants)} "
          f"pending={len(tasks)} done={len(done)}")
    if not tasks:
        report()
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n = 0
    with OUT.open("a", encoding="utf-8") as fh, \
            multiprocessing.Pool(processes=args.workers) as pool:
        for res in pool.imap_unordered(_job, tasks, chunksize=1):
            if res:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
            if time.time() - t0 > args.budget_sec:
                print(f"[bench] budget reached after {n} measurements — re-run to continue")
                break
    print(f"[bench] {n} measurements in {time.time() - t0:.0f}s")
    report()


if __name__ == "__main__":
    main()
