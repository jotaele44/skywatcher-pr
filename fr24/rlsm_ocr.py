"""
RLSM serial OCR runner — single-threaded, resumable.

Processes screenshots with ocr_status='pending' one at a time.  Useful for
debugging a specific image or running inside the sandbox where multiprocessing
is not available.  For bulk runs, prefer fr24.rlsm_ocr_parallel.

CLI:
    python3 -m fr24.rlsm_ocr [--budget-sec 35] [--limit N] [--filter-month YYYY-MM]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Tuple

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
DB   = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
JSONL = REPO / "outputs" / "ocr_raw_by_zone.jsonl"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ocr_zone(img: Image.Image, zone, config: str) -> Tuple[str, list, float, float, int]:
    """Return (raw_text, lines_json, conf_mean, conf_min, n_words)."""
    crop = img.crop(zone.crop_box())
    if pytesseract is None:
        return "", [], 0.0, 0.0, 0
    try:
        data = pytesseract.image_to_data(
            crop, config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return "", [], 0.0, 0.0, 0
    words = [w for w in data["text"] if w.strip()]
    confs = [c for c, w in zip(data["conf"], data["text"]) if w.strip() and c >= 0]
    raw_text = " ".join(words)
    conf_mean = float(sum(confs) / len(confs)) if confs else 0.0
    conf_min  = float(min(confs)) if confs else 0.0
    return raw_text, [], conf_mean, conf_min, len(words)


def process_screenshot(conn: sqlite3.Connection, sid: int, rel_path: str,
                       run_id: int) -> dict:
    """OCR one screenshot; write ocr_observations rows; update screenshots.ocr_status."""
    from fr24.rlsm_zones import zones_for, ZONE_OCR_CONFIG

    full_path = REPO / rel_path
    if not full_path.exists():
        conn.execute("UPDATE screenshots SET ocr_status='failed' WHERE screenshot_id=?", (sid,))
        conn.commit()
        return {"ok": False, "reason": "missing"}

    try:
        with Image.open(full_path) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            W, H = img.size
            zones = zones_for(W, H)

        n_obs = 0
        for zone in zones:
            cfg = ZONE_OCR_CONFIG.get(zone.name, {"psm": 6, "preprocess": "high_contrast"})
            psm = cfg.get("psm", 6)
            config = f"--oem 1 --psm {psm}"
            with Image.open(full_path) as img2:
                img2 = ImageOps.exif_transpose(img2)
                raw_text, lines_json, conf_mean, conf_min, n_words = _ocr_zone(img2, zone, config)
            bbox = zone.crop_box()
            z_status = "ok" if raw_text.strip() else "empty"
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
                     None, psm, z_status, None, _iso_now()),
                )
                n_obs += 1
            except sqlite3.IntegrityError:
                pass

        conn.execute("UPDATE screenshots SET ocr_status='ok' WHERE screenshot_id=?", (sid,))
        conn.commit()
        return {"ok": True, "n_obs": n_obs}

    except Exception as exc:
        conn.execute("UPDATE screenshots SET ocr_status='failed' WHERE screenshot_id=?", (sid,))
        conn.commit()
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}


def run(budget_sec: float, limit: int = 0, filter_month: str = "") -> None:
    JSONL.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s for the write lock (concurrency-safe)

    where = ["s.ingest_status = 'ok'",
             "s.ocr_status = 'pending'"]
    params = []
    if filter_month:
        where.append("s.month_bucket = ?")
        params.append(filter_month)

    sql = ("SELECT s.screenshot_id, s.rel_path FROM screenshots s WHERE "
           + " AND ".join(where)
           + " ORDER BY s.screenshot_id")
    if limit:
        sql += f" LIMIT {limit}"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("[rlsm_ocr] no pending screenshots")
        conn.close()
        return

    n_inputs = len(rows)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('ocr', ?, 'in_progress', ?, 0, 0)",
        (_iso_now(), n_inputs),
    )
    run_id = cur.lastrowid
    conn.commit()

    t0 = time.time()
    n_ok = n_fail = 0
    for sid, rel_path in rows:
        if time.time() - t0 > budget_sec:
            break
        result = process_screenshot(conn, sid, rel_path, run_id)
        if result.get("ok"):
            n_ok += 1
        else:
            n_fail += 1
        if (n_ok + n_fail) % 50 == 0:
            elapsed = time.time() - t0
            rate = (n_ok + n_fail) / elapsed if elapsed else 0
            print(f"[rlsm_ocr] {n_ok + n_fail}/{n_inputs}"
                  f"  ok={n_ok} fail={n_fail}"
                  f"  rate={rate:.2f} img/s", flush=True)

    elapsed = time.time() - t0
    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=?, n_failed=? WHERE run_id=?",
        (_iso_now(), n_ok, n_fail, run_id),
    )
    conn.commit()
    conn.close()
    print(json.dumps({
        "run_id": run_id, "targets": n_inputs,
        "processed": n_ok, "failed": n_fail,
        "elapsed_sec": round(elapsed, 2),
    }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec",   type=float, default=35.0)
    ap.add_argument("--limit",        type=int,   default=0)
    ap.add_argument("--filter-month", type=str,   default="")
    args = ap.parse_args()
    run(args.budget_sec, args.limit, args.filter_month)


if __name__ == "__main__":
    main()
