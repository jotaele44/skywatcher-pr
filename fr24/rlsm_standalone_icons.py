"""Detect provisional standalone map and GUI icons without requiring OCR labels.

This pass is deliberately review-first: candidates are stored with ``pin_id``
NULL, an explicit provisional class, and ``review_status='needs_review'``.
They are not promoted to confirmed POIs or geographic features.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
METHOD = "standalone_tiled_salience_v1"

RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS icon_scan_receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id INTEGER REFERENCES processing_runs(run_id),
    method TEXT NOT NULL,
    scan_status TEXT NOT NULL,
    regions_scanned INTEGER NOT NULL,
    windows_scanned INTEGER NOT NULL,
    candidates_inserted INTEGER NOT NULL,
    scan_error TEXT,
    observed_at TEXT NOT NULL,
    UNIQUE(screenshot_id, method)
);
CREATE INDEX IF NOT EXISTS ix_icon_scan_status ON icon_scan_receipts(scan_status);
"""

TILE_SIZE = 64
STRIDE = 48
MAX_CANDIDATES_PER_SCREENSHOT = 60
MIN_CONFIDENCE = 0.38


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_schema(conn: sqlite3.Connection) -> None:
    from fr24.rlsm_icons import ensure_schema as ensure_icon_schema
    ensure_icon_schema(conn)
    conn.executescript(RECEIPT_SCHEMA)
    conn.commit()


def _grid(image: Any, box: tuple[int, int, int, int]) -> list[list[tuple[int, int, int]]]:
    crop = image.crop(box)
    width, height = crop.size
    pixels = list(crop.getdata())
    return [pixels[y * width:(y + 1) * width] for y in range(height)]


def _regions(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    if height >= width:
        return [
            ("map", (0, int(height * 0.05), width, int(height * 0.65))),
            ("top_gui", (0, 0, width, int(height * 0.13))),
            ("bottom_gui", (0, int(height * 0.72), width, height)),
        ]
    return [
        ("map", (0, int(height * 0.08), int(width * 0.70), int(height * 0.95))),
        ("top_gui", (0, 0, width, int(height * 0.14))),
        ("side_gui", (int(width * 0.68), int(height * 0.08), width, height)),
        ("bottom_gui", (0, int(height * 0.82), width, height)),
    ]


def _windows(box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    x0, y0, x1, y1 = box
    windows: list[tuple[int, int, int, int]] = []
    y = y0
    while y < y1:
        x = x0
        wy1 = min(y1, y + TILE_SIZE)
        while x < x1:
            wx1 = min(x1, x + TILE_SIZE)
            if wx1 - x >= 16 and wy1 - y >= 16:
                windows.append((x, y, wx1, wy1))
            if wx1 == x1:
                break
            x += STRIDE
        if wy1 == y1:
            break
        y += STRIDE
    return windows


def _overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    smaller = min(aw * ah, bw * bh)
    return intersection / smaller if smaller else 0.0


def _near_existing(candidate: tuple[int, int, int, int], existing: list[tuple[int, int, int, int]]) -> bool:
    cx, cy = candidate[0] + candidate[2] / 2, candidate[1] + candidate[3] / 2
    for box in existing:
        bx, by = box[0] + box[2] / 2, box[1] + box[3] / 2
        distance = math.hypot(cx - bx, cy - by)
        radius = max(12.0, max(candidate[2], candidate[3], box[2], box[3]) * 0.8)
        if distance <= radius or _overlap_ratio(candidate, box) >= 0.4:
            return True
    return False


def _existing_boxes(conn: sqlite3.Connection, sid: int) -> list[tuple[int, int, int, int]]:
    rows = conn.execute(
        """SELECT bbox_x, bbox_y, bbox_w, bbox_h FROM icon_observations
           WHERE screenshot_id=? AND bbox_x IS NOT NULL AND bbox_y IS NOT NULL
             AND bbox_w IS NOT NULL AND bbox_h IS NOT NULL""",
        (sid,),
    ).fetchall()
    return [tuple(map(int, row)) for row in rows]


def _receipt(conn: sqlite3.Connection, *, sid: int, run_id: int, status: str, regions: int, windows: int, candidates: int, error: str | None) -> None:
    conn.execute(
        """INSERT INTO icon_scan_receipts
           (screenshot_id, run_id, method, scan_status, regions_scanned,
            windows_scanned, candidates_inserted, scan_error, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(screenshot_id, method) DO UPDATE SET
               run_id=excluded.run_id, scan_status=excluded.scan_status,
               regions_scanned=excluded.regions_scanned,
               windows_scanned=excluded.windows_scanned,
               candidates_inserted=excluded.candidates_inserted,
               scan_error=excluded.scan_error, observed_at=excluded.observed_at""",
        (sid, run_id, METHOD, status, regions, windows, candidates, error, _iso_now()),
    )


def scan_screenshot(conn: sqlite3.Connection, sid: int, rel_path: str, run_id: int) -> dict[str, Any]:
    from fr24.rlsm_icons import detect_in_window

    if Image is None or ImageOps is None:
        _receipt(conn, sid=sid, run_id=run_id, status="failed", regions=0, windows=0, candidates=0, error="pillow_not_installed")
        conn.commit()
        return {"ok": False, "windows": 0, "candidates": 0}
    source = REPO / rel_path
    if not source.exists():
        _receipt(conn, sid=sid, run_id=run_id, status="failed", regions=0, windows=0, candidates=0, error="source_image_missing")
        conn.commit()
        return {"ok": False, "windows": 0, "candidates": 0}
    try:
        with Image.open(source) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            rgb_image = image.convert("RGB")
            hsv_image = rgb_image.convert("HSV")
            regions = _regions(*rgb_image.size)
            existing = _existing_boxes(conn, sid)
            accepted: list[tuple[int, int, int, int]] = []
            window_count = inserted = 0
            for region_type, region_box in regions:
                for window in _windows(region_box):
                    window_count += 1
                    feature = detect_in_window(_grid(rgb_image, window), _grid(hsv_image, window))
                    if feature is None:
                        continue
                    x, y = window[0] + int(feature["x"]), window[1] + int(feature["y"])
                    box = (x, y, int(feature["w"]), int(feature["h"]))
                    if _near_existing(box, existing + accepted):
                        continue
                    confidence = round(min(0.68, MIN_CONFIDENCE + float(feature["fill_ratio"]) * 0.25), 3)
                    icon_class = "unclassified_map_icon" if region_type == "map" else "unclassified_gui_icon"
                    conn.execute(
                        """INSERT INTO icon_observations
                           (screenshot_id, pin_id, run_id, bbox_x, bbox_y,
                            bbox_w, bbox_h, centroid_x, centroid_y, area_px,
                            aspect, fill_ratio, hue_deg, saturation, value,
                            ahash, cluster_id, icon_class, confidence,
                            review_status, observed_at)
                           VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                   ?, ?, NULL, ?, ?, 'needs_review', ?)""",
                        (sid, run_id, x, y, feature["w"], feature["h"],
                         x + feature["w"] // 2, y + feature["h"] // 2,
                         feature["area"], feature["aspect"], feature["fill_ratio"],
                         feature["hue_deg"], feature["saturation"], feature["value"],
                         feature["ahash"], icon_class, confidence, _iso_now()),
                    )
                    accepted.append(box)
                    inserted += 1
                    if inserted >= MAX_CANDIDATES_PER_SCREENSHOT:
                        break
                if inserted >= MAX_CANDIDATES_PER_SCREENSHOT:
                    break
        _receipt(conn, sid=sid, run_id=run_id, status="ok", regions=len(regions), windows=window_count, candidates=inserted, error=None)
        conn.commit()
        return {"ok": True, "windows": window_count, "candidates": inserted}
    except Exception as exc:
        _receipt(conn, sid=sid, run_id=run_id, status="failed", regions=0, windows=0, candidates=0, error=f"{type(exc).__name__}: {exc}"[:500])
        conn.commit()
        return {"ok": False, "windows": 0, "candidates": 0}


def run(budget_sec: float = 86400.0, limit: int = 0) -> dict[str, Any]:
    if not DB.exists():
        raise FileNotFoundError(f"RLSM DB not found: {DB}")
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(conn)
    sql = """SELECT s.screenshot_id, s.rel_path FROM screenshots s
             WHERE s.ingest_status='ok' AND NOT EXISTS (
                 SELECT 1 FROM icon_scan_receipts r
                 WHERE r.screenshot_id=s.screenshot_id AND r.method=?
             ) ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (METHOD,)).fetchall()
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('standalone_icon_detect', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), len(rows), json.dumps({"method": METHOD})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()
    start = time.monotonic()
    processed = failed = windows = candidates = 0
    for sid, rel_path in rows:
        if time.monotonic() - start > budget_sec:
            break
        result = scan_screenshot(conn, int(sid), str(rel_path), run_id)
        processed += 1
        windows += int(result["windows"])
        candidates += int(result["candidates"])
        failed += int(not result["ok"])
    unprocessed = len(rows) - processed
    status = "failed" if unprocessed else "completed"
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (_iso_now(), status, processed, failed + unprocessed,
         json.dumps({"method": METHOD, "windows": windows, "candidates": candidates, "unprocessed": unprocessed}, sort_keys=True), run_id),
    )
    conn.commit()
    conn.close()
    return {"run_id": run_id, "targets": len(rows), "processed": processed, "failed": failed, "unprocessed": unprocessed, "windows": windows, "candidates": candidates, "status": status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(args.budget_sec, args.limit)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["unprocessed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
