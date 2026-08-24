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

from fr24.rlsm_preprocess import preprocess, scale_for  # noqa: E402
from fr24.rlsm_source_availability import (  # noqa: E402
    SourceUnavailableError,
    availability_predicate,
    mark_missing_during_ocr,
    open_stable_source,
    require_availability_schema,
)
from fr24.rlsm_wordboxes import words_from_tesseract_data  # noqa: E402

DB   = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
JSONL = REPO / "outputs" / "ocr_raw_by_zone.jsonl"

_LANG_CACHE: str | None = None
_VERSION_CACHE: str | None = None


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tess_lang() -> str:
    """Prefer ``spa+eng``; see fr24/rlsm_ocr_parallel.py for why."""
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


def _ocr_zone(crop: Image.Image, zone, config: str, mode: str = "none",
              scale: float = 1.0) -> tuple[str, list, float, float, int]:
    """Return (raw_text, word_boxes, conf_mean, conf_min, n_words).

    ``crop`` is the raw zone crop; preprocessing is applied here so the caller
    never has to remember that the ``scale`` it passes on must match the one the
    crop was upscaled by.

    ``word_boxes`` carries the per-word geometry image_to_data already computes;
    see fr24/rlsm_wordboxes.py for why it is kept rather than discarded.
    """
    crop = preprocess(crop, mode, scale)
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
    confs = [c for c, w in zip(data["conf"], data["text"], strict=True) if w.strip() and c >= 0]
    raw_text = " ".join(words)
    conf_mean = float(sum(confs) / len(confs)) if confs else 0.0
    conf_min  = float(min(confs)) if confs else 0.0
    boxes = words_from_tesseract_data(data, x_off=zone.x, y_off=zone.y,
                                      scale=scale if mode != "none" else 1.0)
    return raw_text, boxes, conf_mean, conf_min, len(words)


def _build_target_query(filter_month: str = "", limit: int = 0) -> tuple[str, list]:
    where = [
        "s.ingest_status = 'ok'",
        "s.ocr_status = 'pending'",
        availability_predicate("s"),
    ]
    params: list[str] = []
    if filter_month:
        where.append("s.month_bucket = ?")
        params.append(filter_month)
    sql = (
        "SELECT s.screenshot_id, s.rel_path FROM screenshots s WHERE "
        + " AND ".join(where)
        + " ORDER BY s.screenshot_id"
    )
    if limit:
        sql += f" LIMIT {limit}"
    return sql, params


def process_screenshot(
    conn: sqlite3.Connection,
    sid: int,
    rel_path: str,
    run_id: int,
) -> dict:
    """OCR one stable source; missing/unstable input remains pending."""
    from fr24.rlsm_zones import ZONE_OCR_CONFIG, zones_for

    full_path = REPO / rel_path
    try:
        with (
            open_stable_source(full_path) as source_handle,
            Image.open(source_handle) as img,
        ):
            img.load()
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            zones = zones_for(width, height)
            crops = {zone.name: img.crop(zone.crop_box()) for zone in zones}

        lang = _tess_lang()
        engine_version = _tess_version()
        n_obs = 0
        for zone in zones:
            cfg = ZONE_OCR_CONFIG.get(
                zone.name,
                {"psm": 6, "preprocess": "high_contrast"},
            )
            psm = cfg.get("psm", 6)
            mode = cfg.get("preprocess", "none")
            scale = scale_for(mode, cfg.get("scale"))
            config = f"--oem 1 --psm {psm} -l {lang}"
            raw_text, lines_json, conf_mean, conf_min, n_words = _ocr_zone(
                crops[zone.name],
                zone,
                config,
                mode=mode,
                scale=scale,
            )
            bbox = zone.crop_box()
            zone_status = "ok" if raw_text.strip() else "empty"
            try:
                conn.execute(
                    """
                    INSERT INTO ocr_observations
                        (screenshot_id, run_id, zone, bbox_x, bbox_y, bbox_w, bbox_h,
                         raw_text, raw_lines_json, confidence_mean, confidence_min,
                         n_words, engine, engine_version, psm, preprocess,
                         preprocess_scale, ocr_status, ocr_error, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tesseract',
                            ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        run_id,
                        zone.name,
                        bbox[0],
                        bbox[1],
                        bbox[2] - bbox[0],
                        bbox[3] - bbox[1],
                        raw_text,
                        json.dumps(lines_json, ensure_ascii=False),
                        conf_mean,
                        conf_min,
                        n_words,
                        engine_version,
                        psm,
                        mode,
                        scale,
                        zone_status,
                        None,
                        _iso_now(),
                    ),
                )
                n_obs += 1
            except sqlite3.IntegrityError:
                pass

        conn.execute(
            "UPDATE screenshots SET ocr_status='ok' WHERE screenshot_id=?",
            (sid,),
        )
        conn.commit()
        return {"ok": True, "n_obs": n_obs}
    except (FileNotFoundError, SourceUnavailableError):
        mark_missing_during_ocr(conn, sid)
        return {"ok": False, "reason": "missing_source"}
    except OSError as exc:
        if exc.errno in {2, 20, 116}:
            mark_missing_during_ocr(conn, sid)
            return {"ok": False, "reason": "missing_source"}
        conn.execute(
            "UPDATE screenshots SET ocr_status='failed' WHERE screenshot_id=?",
            (sid,),
        )
        conn.commit()
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}
    except Exception as exc:
        conn.execute(
            "UPDATE screenshots SET ocr_status='failed' WHERE screenshot_id=?",
            (sid,),
        )
        conn.commit()
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}



def run(budget_sec: float, limit: int = 0, filter_month: str = "") -> None:
    JSONL.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s for the write lock (concurrency-safe)

    require_availability_schema(conn)
    sql, params = _build_target_query(filter_month, limit)
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
    n_ok = n_fail = n_missing = 0
    for sid, rel_path in rows:
        if time.time() - t0 > budget_sec:
            break
        result = process_screenshot(conn, sid, rel_path, run_id)
        if result.get("ok"):
            n_ok += 1
        elif result.get("reason") == "missing_source":
            n_missing += 1
        else:
            n_fail += 1
        n_seen = n_ok + n_fail + n_missing
        if n_seen % 50 == 0:
            elapsed = time.time() - t0
            rate = n_seen / elapsed if elapsed else 0
            print(f"[rlsm_ocr] {n_seen}/{n_inputs}"
                  f"  ok={n_ok} fail={n_fail} missing={n_missing}"
                  f"  rate={rate:.2f} img/s", flush=True)

    elapsed = time.time() - t0
    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_processed=?, n_failed=?, notes=? WHERE run_id=?",
        (_iso_now(), n_ok, n_fail,
         json.dumps({"missing_source": n_missing}, sort_keys=True), run_id),
    )
    conn.commit()
    conn.close()
    print(json.dumps({
        "run_id": run_id, "targets": n_inputs,
        "processed": n_ok, "failed": n_fail,
        "missing_source": n_missing,
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
