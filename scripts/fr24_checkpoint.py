#!/usr/bin/env python3
"""
FR24 Checkpoint Runner
Processes Flight Logs images in batches with checkpoint/resume support.
Run repeatedly until DONE is printed.

Usage:
  python run_fr24_checkpoint.py [--batch N] [--reset]
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent
DATA_DIR = REPO / "data" / "Flight Logs"
# Use /tmp for SQLite + checkpoint (virtiofs mount has WAL I/O issues)
DB_PATH = Path("/tmp/flights.db")
CHECKPOINT = Path("/tmp/fr24_scan_checkpoint.json")
INVENTORY_CSV = Path("/tmp/screenshot_inventory.csv")
SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".heic"}

BATCH = 900   # images per call — inventory-only mode (~34s @ 0.038s/img)


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {
        "processed_idx": 0,
        "total_files": 0,
        "stats": {"total": 0, "valid": 0, "corrupt": 0, "duplicates": 0,
                  "screenshots_upserted": 0, "track_points_inserted": 0},
        "hash_index": {},   # sha256 -> first path
        "started_at": datetime.utcnow().isoformat(),
    }


def save_checkpoint(cp):
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(cp, indent=2))


def ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS screenshots (
            screenshot_id TEXT PRIMARY KEY,
            image_path TEXT, flight_id TEXT, processed_at TEXT,
            callsign TEXT, altitude_ft INTEGER, ground_speed_mph INTEGER,
            latitude REAL, longitude REAL, timestamp TEXT,
            raw_text TEXT, ocr_confidence REAL, sha256 TEXT,
            coordinate_method TEXT, coordinate_confidence REAL,
            estimated_error_m REAL, review_status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT, timestamp TEXT,
            latitude REAL, longitude REAL,
            altitude_ft INTEGER, ground_speed_mph INTEGER
        );
    """)
    conn.commit()


def inspect_image(path: Path, hash_index: dict):
    """Hash, dimension-check, and duplicate-detect one image."""
    try:
        raw = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
    except OSError:
        return {"path": str(path), "sha256": None,
                "is_corrupt": True, "is_duplicate": False}

    width = height = None
    is_corrupt = False
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
    except Exception:
        is_corrupt = True

    is_duplicate = sha256 in hash_index
    if not is_duplicate:
        hash_index[sha256] = str(path)

    return {
        "path": str(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256,
        "width": width,
        "height": height,
        "is_corrupt": is_corrupt,
        "is_duplicate": is_duplicate,
        "duplicate_of": hash_index.get(sha256) if is_duplicate else None,
        "scanned_at": datetime.utcnow().isoformat() + "Z",
    }


def upsert_screenshot(conn, rec, now):
    sha256 = rec.get("sha256")
    if not sha256 or rec.get("is_corrupt") or rec.get("is_duplicate"):
        return 0
    conn.execute(
        """INSERT OR IGNORE INTO screenshots
           (screenshot_id, image_path, processed_at, sha256,
            coordinate_method, coordinate_confidence, estimated_error_m, review_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sha256, rec["path"], now, sha256,
         "fixed_pr_bounds", 0.65, 1500.0, "pending"),
    )
    return conn.execute("SELECT changes()").fetchone()[0]


def extract_and_insert_routes(conn, rec, now):
    """Attempt route extraction; silently skip on any error."""
    try:
        from fr24.ui_segmenter import FR24UISegmenter
        from fr24.route_extractor import RouteExtractor
        from integration.geo_calibration import GeoCalibration
        from PIL import Image as PILImage

        seg = FR24UISegmenter(mode="geometric")
        ext = RouteExtractor(segmenter=seg)
        routes = ext.extract(rec["path"])
        if not routes:
            return 0

        with PILImage.open(rec["path"]) as img:
            img_w, img_h = img.size
        cal = GeoCalibration(mode="fixed_pr_bounds")

        inserted = 0
        for route in routes:
            if route.confidence < 0.10:
                continue
            pts = route.points
            step = max(1, len(pts) // 30)
            sampled = pts[::step][:30]
            for px, py in sampled:
                coord = cal.pixel_to_coord(px, py, img_w, img_h)
                if not coord.in_pr_bbox():
                    continue
                conn.execute(
                    "INSERT INTO track_points (flight_id, timestamp, latitude, longitude, altitude_ft, ground_speed_mph) VALUES (?,?,?,?,?,?)",
                    (rec.get("sha256"), now, coord.lat, coord.lon, 0, 0),
                )
                inserted += 1
        return inserted
    except Exception:
        return 0


def write_csv_header(path: Path):
    import csv
    fields = ["path", "filename", "size_bytes", "sha256", "width", "height",
              "is_corrupt", "is_duplicate", "duplicate_of", "scanned_at"]
    with open(path, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()


def append_csv(path: Path, records):
    import csv
    fields = ["path", "filename", "size_bytes", "sha256", "width", "height",
              "is_corrupt", "is_duplicate", "duplicate_of", "scanned_at"]
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writerows(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--reset", action="store_true", help="Clear checkpoint and restart")
    parser.add_argument("--no-routes", action="store_true", default=True,
                        help="Skip route extraction (inventory-only mode, default)")
    parser.add_argument("--with-routes", action="store_true",
                        help="Enable route extraction (slow, use for final pass)")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and CHECKPOINT.exists():
        CHECKPOINT.unlink()
        if INVENTORY_CSV.exists():
            INVENTORY_CSV.unlink()
        if DB_PATH.exists():
            DB_PATH.unlink()
        print("  Checkpoint cleared — starting fresh")

    cp = load_checkpoint()

    # Collect all image files once (sorted for determinism)
    all_files = sorted(
        p for p in DATA_DIR.rglob("*")
        if p.suffix.lower() in SUPPORTED
    )

    if cp["total_files"] == 0:
        cp["total_files"] = len(all_files)
        write_csv_header(INVENTORY_CSV)
        save_checkpoint(cp)
        print(f"  Discovered {len(all_files):,} image files")

    start_idx = cp["processed_idx"]
    end_idx = min(start_idx + args.batch, len(all_files))
    batch = all_files[start_idx:end_idx]

    if not batch:
        print(f"\n{'='*60}")
        print("  DONE — all images processed")
        s = cp["stats"]
        print(f"  Total:               {s['total']:>8,}")
        print(f"  Valid:               {s['valid']:>8,}")
        print(f"  Corrupt:             {s['corrupt']:>8,}")
        print(f"  Duplicates:          {s['duplicates']:>8,}")
        print(f"  Screenshots in DB:   {s['screenshots_upserted']:>8,}")
        print(f"  Track points in DB:  {s['track_points_inserted']:>8,}")
        print(f"  DB:                  {DB_PATH}")
        print(f"  Inventory CSV:       {INVENTORY_CSV}")
        print(f"{'='*60}")
        return

    print(f"\n  FR24 CHECKPOINT SCAN — batch {start_idx}–{end_idx-1} of {len(all_files):,}")
    print(f"  {'─'*55}")

    conn = sqlite3.connect(str(DB_PATH))
    ensure_schema(conn)
    now = datetime.utcnow().isoformat() + "Z"

    t0 = time.time()
    records = []
    hash_index = cp["hash_index"]

    batch_stats = {"total": 0, "valid": 0, "corrupt": 0,
                   "duplicates": 0, "upserted": 0, "track_pts": 0}

    for path in batch:
        rec = inspect_image(path, hash_index)
        records.append(rec)
        batch_stats["total"] += 1

        if rec["is_corrupt"]:
            batch_stats["corrupt"] += 1
        elif rec["is_duplicate"]:
            batch_stats["duplicates"] += 1
        else:
            batch_stats["valid"] += 1
            n = upsert_screenshot(conn, rec, now)
            batch_stats["upserted"] += n
            if n and args.with_routes:
                batch_stats["track_pts"] += extract_and_insert_routes(conn, rec, now)

    conn.commit()
    conn.close()

    append_csv(INVENTORY_CSV, records)

    # Update checkpoint
    cp["processed_idx"] = end_idx
    cp["hash_index"] = hash_index
    for k, v in batch_stats.items():
        if k == "upserted":
            cp["stats"]["screenshots_upserted"] += v
        elif k == "track_pts":
            cp["stats"]["track_points_inserted"] += v
        else:
            cp["stats"][k] += v

    save_checkpoint(cp)

    elapsed = time.time() - t0
    pct = end_idx / len(all_files) * 100
    remaining = len(all_files) - end_idx
    eta_s = remaining * (elapsed / len(batch)) if batch else 0

    print(f"  Batch done in {elapsed:.1f}s")
    print(f"  Progress:  {end_idx:,} / {len(all_files):,}  ({pct:.1f}%)")
    print(f"  This batch → total: {batch_stats['valid']} valid, "
          f"{batch_stats['corrupt']} corrupt, {batch_stats['duplicates']} dupes")
    print(f"  Cumulative → screenshots in DB: {cp['stats']['screenshots_upserted']:,}, "
          f"track pts: {cp['stats']['track_points_inserted']:,}")
    print(f"  ETA (full scan): ~{eta_s/60:.1f} min more")
    if end_idx >= len(all_files):
        print(f"\n  ALL FILES PROCESSED ✓  (DB: {DB_PATH})")
    else:
        print(f"\n  Run again to continue from image {end_idx:,}")


if __name__ == "__main__":
    main()
