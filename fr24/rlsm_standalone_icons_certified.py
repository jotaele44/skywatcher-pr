"""Conservative standalone icon extraction with recurrence and explicit truncation receipts."""
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

# The legacy detector silently stopped at 60 insertions per frame. This runner
# instead keeps a bounded, ranked candidate set and records budget exhaustion as
# an explicit ``truncated`` receipt. Truncation is reviewable, not a fake failure.
DETECTION_BUDGET_PER_SCREENSHOT = 96
REPRESENTATIVE_CAP_PER_SCREENSHOT = 32
PERSIST_CAP_PER_SCREENSHOT = 12
MIN_DISTINCT_SCREENSHOTS = 2


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _grid(
    image: Any,
    box: tuple[int, int, int, int],
) -> list[list[tuple[int, int, int]]]:
    crop = image.crop(box)
    width, height = crop.size
    pixels = list(crop.getdata())
    return [pixels[y * width : (y + 1) * width] for y in range(height)]


def _touches_window_border(
    feature: dict[str, Any],
    window: tuple[int, int, int, int],
    margin: int = 2,
) -> bool:
    width = window[2] - window[0]
    height = window[3] - window[1]
    x = int(feature["x"])
    y = int(feature["y"])
    right = x + int(feature["w"])
    bottom = y + int(feature["h"])
    return x <= margin or y <= margin or right >= width - margin or bottom >= height - margin


def _plausible(
    feature: dict[str, Any],
    window: tuple[int, int, int, int],
    region_type: str = "map",
) -> bool:
    width = int(feature["w"])
    height = int(feature["h"])
    area = int(feature["area"])
    aspect = float(feature["aspect"])
    fill = float(feature["fill_ratio"])
    saturation = float(feature["saturation"])
    value = float(feature["value"])
    window_area = max(1, (window[2] - window[0]) * (window[3] - window[1]))

    if not (
        5 <= width <= 38
        and 5 <= height <= 38
        and 24 <= area <= 500
        and aspect <= 2.6
        and 0.22 <= fill <= 0.88
        and area / window_area <= 0.18
        and not _touches_window_border(feature, window)
    ):
        return False

    if region_type == "map":
        # The map is texture-heavy. Require real chroma so roads, coastlines,
        # labels, and tile seams do not dominate the standalone channel.
        return saturation >= 0.22 and 0.10 <= value <= 0.98

    # GUI glyphs may be monochrome, but must be strongly separated from mid-tone
    # chrome when they do not carry colour.
    return saturation >= 0.10 or value <= 0.16 or value >= 0.90


def _overlap_ratio(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    smaller = min(aw * ah, bw * bh)
    return intersection / smaller if smaller else 0.0


def _near(
    candidate: tuple[int, int, int, int],
    boxes: list[tuple[int, int, int, int]],
) -> bool:
    cx = candidate[0] + candidate[2] / 2
    cy = candidate[1] + candidate[3] / 2
    for bx, by, bw, bh in boxes:
        ox = bx + bw / 2
        oy = by + bh / 2
        radius = max(8.0, 0.55 * max(candidate[2], candidate[3], bw, bh))
        if math.hypot(cx - ox, cy - oy) <= radius:
            return True
        if _overlap_ratio(candidate, (bx, by, bw, bh)) >= 0.25:
            return True
    return False


def _score(
    feature: dict[str, Any],
    window: tuple[int, int, int, int],
    region_type: str,
) -> float:
    width = int(feature["w"])
    height = int(feature["h"])
    x = int(feature["x"])
    y = int(feature["y"])
    margin = min(
        x,
        y,
        window[2] - window[0] - (x + width),
        window[3] - window[1] - (y + height),
    )
    fill = float(feature["fill_ratio"])
    saturation = float(feature["saturation"])
    value = float(feature["value"])
    area = max(1, int(feature["area"]))
    size_term = max(0.0, 1.0 - abs(math.sqrt(area) - 14.0) / 14.0)
    contrast = abs(value - 0.5) * 2.0
    gui_bonus = contrast * 0.35 if region_type != "map" else 0.0
    return round(
        saturation * 2.0
        + fill * 1.3
        + size_term * 0.5
        + min(max(margin, 0), 8) / 16.0
        + gui_bonus,
        6,
    )


def _key(feature: dict[str, Any]) -> tuple[str, int, int, int, int, str]:
    hue_bucket = int(round(float(feature["hue_deg"]) / 30.0)) % 12
    width_bucket = int(round(int(feature["w"]) / 4.0))
    height_bucket = int(round(int(feature["h"]) / 4.0))
    fill_bucket = int(round(float(feature["fill_ratio"]) * 10.0))
    return (
        str(feature["ahash"]),
        hue_bucket,
        width_bucket,
        height_bucket,
        fill_bucket,
        str(feature["region_type"]),
    )


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
             WHERE s.ingest_status='ok'
               AND (
                   NOT EXISTS (
                       SELECT 1 FROM icon_scan_receipts r
                       WHERE r.screenshot_id=s.screenshot_id AND r.method=?
                   )
                   OR EXISTS (
                       SELECT 1 FROM icon_scan_receipts r
                       WHERE r.screenshot_id=s.screenshot_id AND r.method=?
                         AND r.scan_status='failed'
                   )
               )
             ORDER BY s.screenshot_id"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = [
        (int(row[0]), str(row[1]))
        for row in conn.execute(sql, (METHOD, METHOD))
    ]
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
    truncations = 0

    for sid, rel_path in targets:
        if time.monotonic() - start > budget_sec:
            break
        processed += 1
        source = repo_root / rel_path
        if Image is None or ImageOps is None:
            scan_meta[sid] = {
                "status": "failed",
                "regions": 0,
                "windows": 0,
                "error": "pillow_not_installed",
                "raw_detections": 0,
            }
            failures += 1
            continue
        if not source.exists():
            scan_meta[sid] = {
                "status": "failed",
                "regions": 0,
                "windows": 0,
                "error": "source_image_missing",
                "raw_detections": 0,
            }
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
            truncated = False
            with Image.open(source) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                rgb = image.convert("RGB")
                hsv = rgb.convert("HSV")
                regions = legacy._regions(*rgb.size)
                for region_type, region_box in regions:
                    for window in legacy._windows(region_box):
                        window_count += 1
                        feature = detector.detect_in_window(
                            _grid(rgb, window),
                            _grid(hsv, window),
                        )
                        if feature is None or not _plausible(
                            feature,
                            window,
                            region_type,
                        ):
                            continue
                        x = window[0] + int(feature["x"])
                        y = window[1] + int(feature["y"])
                        box = (x, y, int(feature["w"]), int(feature["h"]))
                        if _near(box, existing + boxes):
                            continue
                        candidate = {
                            **feature,
                            "x": x,
                            "y": y,
                            "region_type": region_type,
                            "rel_path": rel_path,
                            "score": _score(feature, window, region_type),
                        }
                        accepted.append(candidate)
                        boxes.append(box)
                        if len(accepted) >= DETECTION_BUDGET_PER_SCREENSHOT:
                            truncated = True
                            break
                    if truncated:
                        break

            ranked = sorted(
                accepted,
                key=lambda candidate: (
                    -float(candidate["score"]),
                    -float(candidate["fill_ratio"]),
                    int(candidate["area"]),
                    int(candidate["y"]),
                    int(candidate["x"]),
                ),
            )[:REPRESENTATIVE_CAP_PER_SCREENSHOT]
            raw_by_screenshot[sid] = ranked
            if truncated:
                truncations += 1
                scan_meta[sid] = {
                    "status": "truncated",
                    "regions": len(regions),
                    "windows": window_count,
                    "error": "candidate_budget_exhausted",
                    "raw_detections": len(accepted),
                }
            else:
                scan_meta[sid] = {
                    "status": "ok",
                    "regions": len(regions),
                    "windows": window_count,
                    "error": None,
                    "raw_detections": len(accepted),
                }
        except Exception as exc:
            scan_meta[sid] = {
                "status": "failed",
                "regions": 0,
                "windows": 0,
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "raw_detections": 0,
            }
            failures += 1

    recurrence: dict[tuple[str, int, int, int, int, str], set[int]] = defaultdict(set)
    for sid, candidates in raw_by_screenshot.items():
        for candidate in candidates:
            recurrence[_key(candidate)].add(sid)

    inserted_by_screenshot: dict[int, int] = defaultdict(int)
    recurrent_keys = {
        key
        for key, screenshot_ids in recurrence.items()
        if len(screenshot_ids) >= MIN_DISTINCT_SCREENSHOTS
    }
    for sid, candidates in raw_by_screenshot.items():
        ranked = sorted(
            (candidate for candidate in candidates if _key(candidate) in recurrent_keys),
            key=lambda candidate: (
                -len(recurrence[_key(candidate)]),
                -float(candidate["score"]),
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
            confidence = round(
                min(
                    0.84,
                    0.44
                    + 0.04 * recurrence_count
                    + 0.03 * min(float(feature["score"]), 3.0),
                ),
                3,
            )
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
            status=str(meta["status"]),
            regions=int(meta["regions"]),
            windows=int(meta["windows"]),
            candidates=int(inserted_by_screenshot[sid]),
            error=str(meta["error"]) if meta["error"] else None,
        )

    unprocessed = len(targets) - processed
    status = "failed" if failures or unprocessed else "completed"
    raw_candidates = sum(len(items) for items in raw_by_screenshot.values())
    raw_detections = sum(
        int(meta.get("raw_detections", 0))
        for meta in scan_meta.values()
    )
    persisted = sum(inserted_by_screenshot.values())
    error_counts: dict[str, int] = defaultdict(int)
    for meta in scan_meta.values():
        if meta.get("error"):
            error_counts[str(meta["error"])] += 1
    notes = {
        "method": METHOD,
        "raw_detections": raw_detections,
        "representative_candidates": raw_candidates,
        "recurrent_keys": len(recurrent_keys),
        "persisted_candidates": persisted,
        "truncations": truncations,
        "errors": dict(sorted(error_counts.items())),
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
        "raw_detections": raw_detections,
        "raw_candidates": raw_candidates,
        "recurrent_keys": len(recurrent_keys),
        "candidates": persisted,
        "truncations": truncations,
        "errors": dict(sorted(error_counts.items())),
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
