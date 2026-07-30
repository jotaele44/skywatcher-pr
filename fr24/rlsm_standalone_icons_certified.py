"""Conservative standalone icon extraction with recurrence and saturation gates."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

from fr24 import rlsm_icons as detector
from fr24 import rlsm_standalone_icons as legacy

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
METHOD = "standalone_recurrent_salience_v2"
RAW_CAP_PER_SCREENSHOT = 24
PERSIST_CAP_PER_SCREENSHOT = 12
MIN_DISTINCT_SCREENSHOTS = 2


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _grid(image: Any, box: tuple[int, int, int, int]) -> list[list[tuple[int, int, int]]]:
    crop = image.crop(box)
    width, height = crop.size
    pixels = list(crop.getdata())
    return [pixels[y * width:(y + 1) * width] for y in range(height)]


def _plausible(feature: dict[str, Any], window: tuple[int, int, int, int]) -> bool:
    width = int(feature["w"])
    height = int(feature["h"])
    area = int(feature["area"])
    aspect = float(feature["aspect"])
    fill = float(feature["fill_ratio"])
    saturation = float(feature["saturation"])
    value = float(feature["value"])
    window_area = max(1, (window[2] - window[0]) * (window[3] - window[1]))
    return (
        4 <= width <= 40
        and 4 <= height <= 40
        and 20 <= area <= 600
        and aspect <= 3.0
        and 0.18 <= fill <= 0.90
        and area / window_area <= 0.25
        and (saturation >= 0.12 or value <= 0.25 or value >= 0.75)
    )


def _near(candidate: tuple[int, int, int, int], boxes: list[tuple[int, int, int, int]]) -> bool:
    cx = candidate[0] + candidate[2] / 2
    cy = candidate[1] + candidate[3] / 2
    for bx, by, bw, bh in boxes:
        ox = bx + bw / 2
        oy = by + bh / 2
        radius = max(10.0, 0.75 * max(candidate[2], candidate[3], bw, bh))
        if math.hypot(cx - ox, cy - oy) <= radius:
            return True
    return False


def _key(feature: dict[str, Any]) -> tuple[str, int]:
    hue_bucket = int(round(float(feature["hue_deg"]) / 30.0)) % 12
    return str(feature["ahash"]), hue_bucket


def _receipt(
    conn: sqlite3.Connection,
    *,
    sid: int,
    run_id: int,
    status: str,
    regions: int,
    windows: int,
    candidates: int,
    error: str | None,
) -> None:
    conn.execute(
        """INSERT INTO icon_scan_receipts
           (screenshot_id, run_id, method, scan_status, regions_scanned,
            windows_scanned, candidates_inserted, scan_error, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(screenshot_id, method) DO UPDATE SET
               run_id=excluded.run_id,
               scan_status=excluded.scan_status,
               regions_scanned=excluded.regions_scanned,
               windows_scanned=excluded.windows_scanned,
               candidates_inserted=excluded.candidates_inserted,
               scan_error=excluded.scan_error,
               observed_at=excluded.observed_at""",
        (sid, run_id, METHOD, status, regions, windows, candidates, error, _iso_now()),
    )


def run(
    *,
    db_path: Path = DB,
    repo_root: Path = REPO,
    budget_sec: float = 86400.0,
    limit: int = 0,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")

    detector.DB = db_path
    detector.REPO = repo_root
    legacy.DB = db_path
    legacy.REPO = repo_root
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    legacy.ensure_schema(conn)
    sql = """SELECT s.screenshot_id, s.rel_path FROM screenshots s
             WHERE s.ingest_status='ok' AND NOT EXISTS (
                 SELECT 1 FROM icon_scan_receipts r
                 WHERE r.screenshot_id=s.screenshot_id AND r.method=?
             ) ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = [(int(row[0]), str(row[1])) for row in conn.execute(sql, (METHOD,))]
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('standalone_icon_certified', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), len(targets), json.dumps({"method": METHOD})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()

    start = time.monotonic()
    raw_by_screenshot: dict[int, list[dict[str, Any]]] = {}
    scan_meta: dict[int, dict[str, Any]] = {}
    failures = 0
    processed = 0

    for sid, rel_path in targets:
        if time.monotonic() - start > budget_sec:
            break
        processed += 1
        source = repo_root / rel_path
        if Image is None or ImageOps is None:
            scan_meta[sid] = {"status": "failed", "regions": 0, "windows": 0, "error": "pillow_not_installed"}
            failures += 1
            continue
        if not source.exists():
            scan_meta[sid] = {"status": "failed", "regions": 0, "windows": 0, "error": "source_image_missing"}
            failures += 1
            continue
        try:
            existing = [
                tuple(map(int, row))
                for row in conn.execute(
                    """SELECT bbox_x, bbox_y, bbox_w, bbox_h FROM icon_observations
                       WHERE screenshot_id=? AND bbox_x IS NOT NULL AND bbox_y IS NOT NULL
                         AND bbox_w IS NOT NULL AND bbox_h IS NOT NULL""",
                    (sid,),
                )
            ]
            accepted: list[dict[str, Any]] = []
            boxes: list[tuple[int, int, int, int]] = []
            window_count = 0
            saturated = False
            with Image.open(source) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                rgb = image.convert("RGB")
                hsv = rgb.convert("HSV")
                regions = legacy._regions(*rgb.size)
                for region_type, region_box in regions:
                    for window in legacy._windows(region_box):
                        window_count += 1
                        feature = detector.detect_in_window(_grid(rgb, window), _grid(hsv, window))
                        if feature is None or not _plausible(feature, window):
                            continue
                        x = window[0] + int(feature["x"])
                        y = window[1] + int(feature["y"])
                        box = (x, y, int(feature["w"]), int(feature["h"]))
                        if _near(box, existing + boxes):
                            continue
                        accepted.append(
                            {
                                **feature,
                                "x": x,
                                "y": y,
                                "region_type": region_type,
                                "rel_path": rel_path,
                            }
                        )
                        boxes.append(box)
                        if len(accepted) >= RAW_CAP_PER_SCREENSHOT:
                            saturated = True
                            break
                    if saturated:
                        break
            if saturated:
                scan_meta[sid] = {
                    "status": "failed",
                    "regions": len(regions),
                    "windows": window_count,
                    "error": "candidate_saturation",
                }
                failures += 1
            else:
                raw_by_screenshot[sid] = accepted
                scan_meta[sid] = {
                    "status": "ok",
                    "regions": len(regions),
                    "windows": window_count,
                    "error": None,
                }
        except Exception as exc:
            scan_meta[sid] = {
                "status": "failed",
                "regions": 0,
                "windows": 0,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
            failures += 1

    recurrence: dict[tuple[str, int], set[int]] = defaultdict(set)
    for sid, candidates in raw_by_screenshot.items():
        for candidate in candidates:
            recurrence[_key(candidate)].add(sid)

    inserted_by_screenshot: dict[int, int] = defaultdict(int)
    recurrent_keys = {
        key for key, screenshot_ids in recurrence.items()
        if len(screenshot_ids) >= MIN_DISTINCT_SCREENSHOTS
    }
    for sid, candidates in raw_by_screenshot.items():
        ranked = sorted(
            (candidate for candidate in candidates if _key(candidate) in recurrent_keys),
            key=lambda candidate: (
                -len(recurrence[_key(candidate)]),
                -float(candidate["fill_ratio"]),
                int(candidate["area"]),
            ),
        )[:PERSIST_CAP_PER_SCREENSHOT]
        for feature in ranked:
            icon_class = (
                "unclassified_map_icon"
                if feature["region_type"] == "map"
                else "unclassified_gui_icon"
            )
            recurrence_count = len(recurrence[_key(feature)])
            confidence = round(min(0.82, 0.46 + 0.04 * recurrence_count), 3)
            conn.execute(
                """INSERT INTO icon_observations
                   (screenshot_id, pin_id, run_id, bbox_x, bbox_y, bbox_w, bbox_h,
                    centroid_x, centroid_y, area_px, aspect, fill_ratio, hue_deg,
                    saturation, value, ahash, cluster_id, icon_class, confidence,
                    review_status, observed_at)
                   VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           NULL, ?, ?, 'needs_review', ?)""",
                (
                    sid,
                    run_id,
                    feature["x"],
                    feature["y"],
                    feature["w"],
                    feature["h"],
                    int(feature["x"]) + int(feature["w"]) // 2,
                    int(feature["y"]) + int(feature["h"]) // 2,
                    feature["area"],
                    feature["aspect"],
                    feature["fill_ratio"],
                    feature["hue_deg"],
                    feature["saturation"],
                    feature["value"],
                    feature["ahash"],
                    icon_class,
                    confidence,
                    _iso_now(),
                ),
            )
            inserted_by_screenshot[sid] += 1

    for sid, _rel_path in targets[:processed]:
        meta = scan_meta[sid]
        _receipt(
            conn,
            sid=sid,
            run_id=run_id,
            status=meta["status"],
            regions=int(meta["regions"]),
            windows=int(meta["windows"]),
            candidates=int(inserted_by_screenshot[sid]),
            error=meta["error"],
        )

    unprocessed = len(targets) - processed
    status = "failed" if failures or unprocessed else "completed"
    raw_candidates = sum(len(items) for items in raw_by_screenshot.values())
    persisted = sum(inserted_by_screenshot.values())
    notes = {
        "method": METHOD,
        "raw_candidates": raw_candidates,
        "recurrent_keys": len(recurrent_keys),
        "persisted_candidates": persisted,
        "saturation_failures": sum(
            1 for meta in scan_meta.values() if meta.get("error") == "candidate_saturation"
        ),
        "unprocessed": unprocessed,
    }
    conn.execute(
        """UPDATE processing_runs SET ended_at=?, status=?, n_inputs=?,
                  n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
        (
            _iso_now(),
            status,
            len(targets),
            processed,
            failures + unprocessed,
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
        "failed": failures,
        "unprocessed": unprocessed,
        "raw_candidates": raw_candidates,
        "recurrent_keys": len(recurrent_keys),
        "candidates": persisted,
        "status": status,
        "method": METHOD,
        "elapsed_sec": round(time.monotonic() - start, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(
            db_path=args.db,
            repo_root=args.repo_root,
            budget_sec=max(1.0, args.budget_sec),
            limit=max(0, args.limit),
        )
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
