"""Fail-closed, resumable OCR runner for the RLSM screenshot corpus.

Unlike the legacy runners, every OCR exception becomes a persisted per-zone
failure receipt. Screenshot status is aggregated as ``ok``, ``partial``, or
``failed``; an empty but successful OCR result remains ``empty`` at zone level.
Raw OCR observations are append-only.
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
from typing import Any

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - explicit runtime receipt
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import pytesseract
except ImportError:  # pragma: no cover - explicit runtime receipt
    pytesseract = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_preprocess import preprocess, scale_for  # noqa: E402
from fr24.rlsm_wordboxes import words_from_tesseract_data  # noqa: E402

DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"

_LANG_CACHE: str | None = None
_VERSION_CACHE: str | None = None


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tess_lang() -> str:
    global _LANG_CACHE
    if _LANG_CACHE is None:
        if pytesseract is None:
            _LANG_CACHE = "unavailable"
        else:
            try:
                langs = set(pytesseract.get_languages(config=""))
            except Exception:
                langs = set()
            if {"spa", "eng"} <= langs:
                _LANG_CACHE = "spa+eng"
            elif "spa" in langs:
                _LANG_CACHE = "spa"
            elif "eng" in langs:
                _LANG_CACHE = "eng"
            else:
                _LANG_CACHE = "unavailable"
    return _LANG_CACHE


def _tess_version() -> str:
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        if pytesseract is None:
            _VERSION_CACHE = "unavailable"
        else:
            try:
                _VERSION_CACHE = str(pytesseract.get_tesseract_version())
            except Exception as exc:
                _VERSION_CACHE = f"unavailable:{type(exc).__name__}"
    return _VERSION_CACHE


def _confidence_values(data: dict[str, list[Any]]) -> list[float]:
    values: list[float] = []
    for raw, text in zip(data.get("conf", []), data.get("text", []), strict=False):
        if not str(text).strip():
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(value)
    return values


def _ocr_zone(
    crop: Any,
    zone: Any,
    *,
    psm: int,
    mode: str,
    scale: float,
    lang: str,
) -> dict[str, Any]:
    """Return one explicit zone receipt; exceptions are data, never empty success."""
    if pytesseract is None:
        return {
            "zone": zone.name,
            "bbox": zone.crop_box(),
            "raw_text": "",
            "word_boxes": [],
            "confidence_mean": 0.0,
            "confidence_min": 0.0,
            "n_words": 0,
            "engine": "tesseract",
            "engine_version": "unavailable",
            "psm": psm,
            "ocr_status": "failed",
            "ocr_error": "pytesseract_not_installed",
        }
    if lang == "unavailable":
        return {
            "zone": zone.name,
            "bbox": zone.crop_box(),
            "raw_text": "",
            "word_boxes": [],
            "confidence_mean": 0.0,
            "confidence_min": 0.0,
            "n_words": 0,
            "engine": "tesseract",
            "engine_version": _tess_version(),
            "psm": psm,
            "ocr_status": "failed",
            "ocr_error": "no_tesseract_language_available",
        }

    try:
        prepared = preprocess(crop, mode, scale)
        config = f"--oem 1 --psm {psm} -l {lang}"
        data = pytesseract.image_to_data(
            prepared,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
        words = [str(word) for word in data.get("text", []) if str(word).strip()]
        confs = _confidence_values(data)
        boxes = words_from_tesseract_data(
            data,
            x_off=zone.x,
            y_off=zone.y,
            scale=scale if mode != "none" else 1.0,
        )
        raw_text = " ".join(words)
        return {
            "zone": zone.name,
            "bbox": zone.crop_box(),
            "raw_text": raw_text,
            "word_boxes": boxes,
            "confidence_mean": sum(confs) / len(confs) if confs else 0.0,
            "confidence_min": min(confs) if confs else 0.0,
            "n_words": len(words),
            "engine": "tesseract",
            "engine_version": _tess_version(),
            "psm": psm,
            "ocr_status": "ok" if raw_text.strip() else "empty",
            "ocr_error": None,
        }
    except Exception as exc:
        return {
            "zone": zone.name,
            "bbox": zone.crop_box(),
            "raw_text": "",
            "word_boxes": [],
            "confidence_mean": 0.0,
            "confidence_min": 0.0,
            "n_words": 0,
            "engine": "tesseract",
            "engine_version": _tess_version(),
            "psm": psm,
            "ocr_status": "failed",
            "ocr_error": f"{type(exc).__name__}: {exc}"[:500],
        }


def _image_failure(sid: int, rel_path: str, reason: str) -> dict[str, Any]:
    return {
        "screenshot_id": sid,
        "rel_path": rel_path,
        "status": "failed",
        "zones": [
            {
                "zone": "full_frame",
                "bbox": (0, 0, 0, 0),
                "raw_text": "",
                "word_boxes": [],
                "confidence_mean": 0.0,
                "confidence_min": 0.0,
                "n_words": 0,
                "engine": "image_decoder",
                "engine_version": "pillow",
                "psm": None,
                "ocr_status": "failed",
                "ocr_error": reason[:500],
            }
        ],
    }


def _process_one(task: tuple[int, str]) -> dict[str, Any]:
    from fr24.rlsm_zones import ZONE_OCR_CONFIG, zones_for

    sid, rel_path = task
    full_path = REPO / rel_path
    if not full_path.exists():
        return _image_failure(sid, rel_path, "source_image_missing")
    if Image is None or ImageOps is None:
        return _image_failure(sid, rel_path, "pillow_not_installed")

    try:
        with Image.open(full_path) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            zones = zones_for(width, height)
            crops = {zone.name: image.crop(zone.crop_box()) for zone in zones}
    except Exception as exc:
        return _image_failure(sid, rel_path, f"{type(exc).__name__}: {exc}")

    lang = _tess_lang()
    receipts: list[dict[str, Any]] = []
    for zone in zones:
        config = ZONE_OCR_CONFIG.get(
            zone.name,
            {"psm": 6, "preprocess": "high_contrast", "scale": 2.0},
        )
        mode = str(config.get("preprocess", "none"))
        scale = scale_for(mode, config.get("scale"))
        receipts.append(
            _ocr_zone(
                crops[zone.name],
                zone,
                psm=int(config.get("psm", 6)),
                mode=mode,
                scale=scale,
                lang=lang,
            )
        )

    failed = sum(1 for receipt in receipts if receipt["ocr_status"] == "failed")
    if failed == len(receipts):
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "ok"
    return {
        "screenshot_id": sid,
        "rel_path": rel_path,
        "status": status,
        "zones": receipts,
    }


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def _select_targets(
    conn: sqlite3.Connection,
    *,
    retry_failed: bool,
    reocr_boxes: bool,
    filter_month: str | None,
    limit: int,
) -> list[tuple[int, str]]:
    where = ["s.ingest_status='ok'"]
    params: list[Any] = []
    if reocr_boxes:
        where.append(
            """s.screenshot_id IN (
                SELECT o.screenshot_id
                FROM ocr_observations o
                WHERE o.obs_id IN (
                    SELECT MAX(obs_id)
                    FROM ocr_observations
                    WHERE zone='label_layer'
                    GROUP BY screenshot_id
                )
                AND COALESCE(o.raw_lines_json, '') IN ('', '[]')
            )"""
        )
    elif retry_failed:
        where.append("s.ocr_status IN ('pending','failed','partial')")
    else:
        where.append("s.ocr_status='pending'")
    if filter_month:
        where.append("s.month_bucket=?")
        params.append(filter_month)

    sql = (
        "SELECT s.screenshot_id, s.rel_path FROM screenshots s WHERE "
        + " AND ".join(where)
        + " ORDER BY s.screenshot_id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [(int(row[0]), str(row[1])) for row in conn.execute(sql, params)]


def _start_run(conn: sqlite3.Connection, n_inputs: int) -> int:
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('ocr_strict_parallel', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), n_inputs, json.dumps({"contract": "fail_closed_v1"})),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _write_result(
    conn: sqlite3.Connection,
    result: dict[str, Any],
    run_id: int,
) -> None:
    sid = int(result["screenshot_id"])
    observed_at = _iso_now()
    with conn:
        for receipt in result["zones"]:
            x0, y0, x1, y1 = receipt["bbox"]
            conn.execute(
                """INSERT INTO ocr_observations
                   (screenshot_id, run_id, zone, bbox_x, bbox_y, bbox_w, bbox_h,
                    raw_text, raw_lines_json, confidence_mean, confidence_min,
                    n_words, engine, engine_version, psm, ocr_status, ocr_error,
                    observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    run_id,
                    receipt["zone"],
                    int(x0),
                    int(y0),
                    int(x1) - int(x0),
                    int(y1) - int(y0),
                    receipt["raw_text"],
                    json.dumps(receipt["word_boxes"], ensure_ascii=False),
                    float(receipt["confidence_mean"]),
                    float(receipt["confidence_min"]),
                    int(receipt["n_words"]),
                    receipt["engine"],
                    receipt["engine_version"],
                    receipt["psm"],
                    receipt["ocr_status"],
                    receipt["ocr_error"],
                    observed_at,
                ),
            )
        conn.execute(
            "UPDATE screenshots SET ocr_status=? WHERE screenshot_id=?",
            (result["status"], sid),
        )


def run(
    *,
    db_path: Path = DB,
    workers: int = 4,
    budget_sec: float = 86400.0,
    limit: int = 0,
    filter_month: str | None = None,
    retry_failed: bool = False,
    reocr_boxes: bool = False,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")

    conn = _connect(db_path)
    targets = _select_targets(
        conn,
        retry_failed=retry_failed,
        reocr_boxes=reocr_boxes,
        filter_month=filter_month,
        limit=limit,
    )
    if not targets:
        conn.close()
        return {
            "run_id": None,
            "targets": 0,
            "processed": 0,
            "ok": 0,
            "partial": 0,
            "failed": 0,
            "unprocessed": 0,
            "status": "completed",
        }

    run_id = _start_run(conn, len(targets))
    started = time.monotonic()
    counts = {"ok": 0, "partial": 0, "failed": 0}
    processed = 0
    stopped_for_budget = False

    pool = multiprocessing.Pool(processes=max(1, workers))
    try:
        for result in pool.imap_unordered(_process_one, targets, chunksize=1):
            _write_result(conn, result, run_id)
            processed += 1
            counts[result["status"]] += 1
            if processed % 50 == 0:
                print(
                    "[strict-ocr] "
                    f"{processed}/{len(targets)} ok={counts['ok']} "
                    f"partial={counts['partial']} failed={counts['failed']}",
                    flush=True,
                )
            if time.monotonic() - started > budget_sec:
                stopped_for_budget = processed < len(targets)
                if stopped_for_budget:
                    pool.terminate()
                break
        else:
            pool.close()
    finally:
        pool.join()

    unprocessed = len(targets) - processed
    run_status = "failed" if unprocessed else "completed"
    notes = {
        "contract": "fail_closed_v1",
        "ok": counts["ok"],
        "partial": counts["partial"],
        "failed": counts["failed"],
        "unprocessed": unprocessed,
        "budget_exhausted": stopped_for_budget,
    }
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (
            _iso_now(),
            run_status,
            processed,
            counts["failed"] + unprocessed,
            json.dumps(notes, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "targets": len(targets),
        "processed": processed,
        **counts,
        "unprocessed": unprocessed,
        "status": run_status,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--filter-month", default=None)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--reocr-boxes", action="store_true")
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args(argv)

    try:
        result = run(
            db_path=args.db,
            workers=args.workers,
            budget_sec=args.budget_sec,
            limit=args.limit,
            filter_month=args.filter_month,
            retry_failed=args.retry_failed,
            reocr_boxes=args.reocr_boxes,
        )
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["unprocessed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
