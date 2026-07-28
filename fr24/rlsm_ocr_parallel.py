"""
RLSM parallel OCR runner — designed for the user's local Mac, not the sandbox.

multiprocessing.Pool over process_screenshot. Each worker keeps its own SQLite
connection (WAL mode handles concurrent writes). OMP_THREAD_LIMIT=1 per worker
keeps tesseract from competing with itself.

Resumable: only processes screenshots with ocr_status='pending'. Safe to Ctrl-C
and restart.

Usage on your Mac:

    cd ~/Documents/GitHub/spiderweb-pr
    OMP_THREAD_LIMIT=1 python3 -m fr24.rlsm_ocr_parallel --workers 4
                                                         --budget-sec 86400
                                                         [--limit N]
                                                         [--filter-month YYYY-MM]
                                                         [--retry-failed]

Quick numbers (prior session benchmarks, your mileage will vary):

    sandbox single-thread, 6 zones:   ~5.8 s/image  → 19 h for full corpus
    sandbox single-thread, 3 zones:   ~2.8 s/image  →  9 h
    local 4 workers,       3 zones:   ~0.7 s/image  →  ~2 h
                                       (with user_words further tuning ~1.5 h)
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

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # HEIC files unsupported if pillow_heif absent

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = "tesseract"
except ImportError:
    pytesseract = None  # type: ignore

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_wordboxes import words_from_tesseract_data  # noqa: E402

DB   = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
JSONL = REPO / "outputs" / "ocr_raw_by_zone.jsonl"

# Populated per-worker via _worker_init
_worker_db_path: str | None = None


_LANG_CACHE: str | None = None
_VERSION_CACHE: str | None = None


def _tess_lang() -> str:
    """
    Prefer ``spa+eng``. Every toponym in this corpus is Spanish — Bayamon,
    Anasco, Penuelas, Mayaguez — and the English model has no priors for the
    accented forms, which is what the downstream diacritic repair exists to
    clean up. Falls back to ``eng`` when spa traineddata is not installed
    (``brew install tesseract-lang``).
    """
    global _LANG_CACHE
    if _LANG_CACHE is None:
        try:
            langs = set(pytesseract.get_languages(config="")) if pytesseract else set()
        except Exception:
            langs = set()
        if {"spa", "eng"} <= langs:
            _LANG_CACHE = "spa+eng"
        elif "spa" in langs:
            _LANG_CACHE = "spa"
        else:
            _LANG_CACHE = "eng"
    return _LANG_CACHE


def _tess_version() -> str:
    """Recorded per observation so a future Tesseract 5 re-run stays distinguishable."""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        try:
            _VERSION_CACHE = str(pytesseract.get_tesseract_version())
        except Exception:
            _VERSION_CACHE = "unknown"
    return _VERSION_CACHE


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _worker_init(db_path: str) -> None:
    """Initialise per-worker global DB path and import config."""
    global _worker_db_path
    _worker_db_path = db_path
    os.environ["OMP_THREAD_LIMIT"] = "1"


def _ocr_with_conf(img_crop: Image.Image, config: str,
                   x_off: int = 0, y_off: int = 0) -> tuple[str, list, float, float, int]:
    """Run tesseract and return (raw_text, word_boxes, conf_mean, conf_min, n_words).

    ``x_off``/``y_off`` are the crop origin, so the returned word boxes are in
    full-image coordinates. See fr24/rlsm_wordboxes.py.
    """
    if pytesseract is None:
        return "", [], 0.0, 0.0, 0
    try:
        data = pytesseract.image_to_data(
            img_crop, config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return "", [], 0.0, 0.0, 0

    words = [w for w in data["text"] if w.strip()]
    confs = [c for c, w in zip(data["conf"], data["text"], strict=True) if w.strip() and c >= 0]
    raw_text = " ".join(words)
    boxes = words_from_tesseract_data(data, x_off=x_off, y_off=y_off)
    conf_mean = float(sum(confs) / len(confs)) if confs else 0.0
    conf_min  = float(min(confs)) if confs else 0.0
    return raw_text, boxes, conf_mean, conf_min, len(words)


def _process_one(args: tuple[int, str, int]) -> dict:
    """Worker function. Returns (sid, status, n_obs, elapsed_sec, err)."""
    from fr24.rlsm_zones import ZONE_OCR_CONFIG, zones_for

    sid, rel_path, run_id = args
    t0 = time.time()
    full_path = REPO / rel_path

    if not full_path.exists():
        return {"screenshot_id": sid, "status": "missing", "n_obs": 0,
                "elapsed_sec": 0.0, "reason": "missing"}

    conn = sqlite3.connect(_worker_db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        # Decode ONCE. This re-opened and re-decoded the 3-5 MB source file for
        # every zone (four decodes per screenshot); across ~12.3k images that was
        # a large share of the wall time for no benefit.
        with Image.open(full_path) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            W, H = img.size
            zones = zones_for(W, H)
            crops = {z.name: img.crop(z.crop_box()) for z in zones}

        lang = _tess_lang()
        engine_version = _tess_version()
        n_obs = 0
        ocr_status = "ok"
        for zone in zones:
            cfg = ZONE_OCR_CONFIG.get(zone.name, {"psm": 6, "preprocess": "high_contrast"})
            psm = cfg.get("psm", 6)
            mode = cfg.get("preprocess", "none")
            scale = scale_for(mode, cfg.get("scale"))
            config = f"--oem 1 --psm {psm} -l {lang}"

            crop = preprocess(crops[zone.name], mode, scale)

            raw_text, lines_json, conf_mean, conf_min, n_words = _ocr_with_conf(
                crop, config, x_off=zone.x, y_off=zone.y)
            z_status = "ok" if raw_text.strip() else "empty"
            bbox = zone.crop_box()

            try:
                conn.execute(
                    """INSERT INTO ocr_observations
                       (screenshot_id, run_id, zone, bbox_x, bbox_y, bbox_w, bbox_h,
                        raw_text, raw_lines_json, confidence_mean, confidence_min, n_words,
                        engine, engine_version, psm, ocr_status, ocr_error, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tesseract', ?, ?, ?, ?, ?)""",
                    (sid, run_id, zone.name, bbox[0], bbox[1],
                     bbox[2] - bbox[0], bbox[3] - bbox[1],
                     raw_text, json.dumps(lines_json, ensure_ascii=False),
                     conf_mean, conf_min, n_words,
                     engine_version, psm, z_status, None, _iso_now()),
                )
                n_obs += 1
            except sqlite3.IntegrityError:
                pass  # already exists (idempotency)

        conn.execute("UPDATE screenshots SET ocr_status=? WHERE screenshot_id=?",
                     (ocr_status, sid))
        conn.commit()
        elapsed = time.time() - t0
        return {"screenshot_id": sid, "status": "ok", "n_obs": n_obs,
                "elapsed_sec": round(elapsed, 3)}

    except Exception as exc:
        conn.execute("UPDATE screenshots SET ocr_status='failed' WHERE screenshot_id=?", (sid,))
        conn.commit()
        return {"screenshot_id": sid, "status": "failed", "n_obs": 0,
                "elapsed_sec": round(time.time() - t0, 3), "reason": str(exc)[:120]}
    finally:
        conn.close()


def _start_run(db_path: str, n_inputs: int) -> int:
    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('ocr_parallel', ?, 'in_progress', ?, 0, 0)",
        (_iso_now(), n_inputs),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def _finish_run(db_path: str, run_id: int, n_processed: int, n_failed: int,
                per_image_avg_sec: float) -> None:
    notes = json.dumps({"per_image_avg_sec": round(per_image_avg_sec, 3)})
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=?, n_failed=?, notes=? WHERE run_id=?",
        (_iso_now(), n_processed, n_failed, notes, run_id),
    )
    conn.commit()
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers",       type=int,   default=4)
    ap.add_argument("--budget-sec",    type=float, default=86400.0)
    ap.add_argument("--limit",         type=int,   default=0)
    ap.add_argument("--filter-month",  type=str,   default=None)
    ap.add_argument("--retry-failed",  action="store_true",
                    help="Also retry screenshots with ocr_status='failed'.")
    ap.add_argument("--reocr-boxes",   action="store_true",
                    help="Re-OCR screenshots whose stored observations predate "
                         "word-box capture (raw_lines_json empty). Appends rows "
                         "under a new run_id; existing raw OCR is never touched.")
    args = ap.parse_args()

    JSONL.parent.mkdir(parents=True, exist_ok=True)

    # Build the target list
    where_parts = ["s.ingest_status='ok'"]
    params = []
    if args.reocr_boxes:
        # Already-OCR'd screenshots that have no word geometry yet. Selecting on
        # the newest label_layer row per screenshot means a screenshot that has
        # already been re-OCR'd is not picked up twice.
        where_parts.append("""s.screenshot_id IN (
            SELECT o.screenshot_id FROM ocr_observations o
            WHERE o.obs_id IN (
                SELECT MAX(obs_id) FROM ocr_observations
                WHERE zone='label_layer' GROUP BY screenshot_id)
              AND COALESCE(o.raw_lines_json, '') IN ('', '[]')
        )""")
    elif args.retry_failed:
        where_parts.append("s.ocr_status IN ('pending','failed')")
    else:
        where_parts.append("s.ocr_status IN ('pending')")
    if args.filter_month:
        where_parts.append("s.month_bucket = ?")
        params.append(args.filter_month)

    sql = ("SELECT screenshot_id, rel_path FROM screenshots s WHERE "
           + " AND ".join(where_parts)
           + " ORDER BY screenshot_id")
    if args.limit:
        sql += f" LIMIT {args.limit}"

    conn = sqlite3.connect(str(DB), timeout=30.0)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        print("[parallel-ocr] no pending screenshots")
        return

    targets = len(rows)
    print(f"[parallel-ocr] run_id=... targets={targets} workers={args.workers}")
    run_id = _start_run(str(DB), targets)
    print(f"[parallel-ocr] run_id={run_id} targets={targets} workers={args.workers}")

    work = [(sid, rel, run_id) for sid, rel in rows]
    t0 = time.time()
    n_ok = n_fail = 0

    with multiprocessing.Pool(
        processes=args.workers,
        initializer=_worker_init,
        initargs=(str(DB),),
    ) as pool:
        for i, result in enumerate(pool.imap_unordered(_process_one, work, chunksize=1)):
            if time.time() - t0 > args.budget_sec:
                pool.terminate()
                print(f"[parallel-ocr] budget {args.budget_sec}s reached; stopping pool")
                break
            if result.get("status") == "ok":
                n_ok += 1
            else:
                n_fail += 1
            if (i + 1) % 50 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed else 0
                remaining = (targets - i - 1) / rate / 60 if rate else 0
                eta_est = round(remaining, 1)
                print(f"[parallel-ocr] {i+1}/{targets}  ok={n_ok} fail={n_fail}"
                      f"  rate={rate:.2f} img/s  remaining={eta_est} min @ 1.0s/img per worker",
                      flush=True)

    elapsed = time.time() - t0
    per_image_avg_sec = elapsed / (n_ok + n_fail) if (n_ok + n_fail) else 0.0
    _finish_run(str(DB), run_id, n_ok, n_fail, per_image_avg_sec)
    print(f"[parallel-ocr] done; elapsed={round(elapsed,1)}s"
          f"  ok={n_ok} fail={n_fail}"
          f"; per_img_avg={per_image_avg_sec:.3f}s")


if __name__ == "__main__":
    main()
