#!/usr/bin/env python3
"""
Full Phase 0 OCR — background runner.
Processes all Flight Logs subdirectories through FlightAnalyzer (Tesseract OCR).
Designed to run as a background process; writes timestamped progress to stdout/log.

Launch:
  nohup python3 run_ocr_full.py > /tmp/ocr_run.log 2>&1 &
  echo $!  > /tmp/ocr_run.pid

Monitor:
  tail -f /tmp/ocr_run.log
  cat /tmp/ocr_progress.json

Foreground test (2 images):
  python3 run_ocr_full.py --limit 2
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO     = Path(__file__).parent
DATA_DIR = REPO / "data" / "Flight Logs"
DB_PATH  = Path("/tmp/pipeline_full.db")
PID_PATH = Path("/tmp/ocr_run.pid")
PROGRESS = Path("/tmp/ocr_progress.json")

SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}


def log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def build_file_list() -> list[Path]:
    paths = []
    for sub in sorted(DATA_DIR.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.iterdir()):
            if p.suffix.lower() in SUPPORTED:
                paths.append(p)
    return paths


def already_processed(db_path: Path, screenshot_id: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT 1 FROM screenshots WHERE screenshot_id = ?", (screenshot_id,)
    ).fetchone()
    conn.close()
    return row is not None


def count_db_rows(db_path: Path):
    if not db_path.exists():
        return 0, 0
    conn = sqlite3.connect(str(db_path))
    shots   = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
    flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    conn.close()
    return shots, flights


def save_progress(idx: int, total: int, stats: dict):
    PROGRESS.write_text(json.dumps({
        "processed": idx, "total": total,
        "pct": round(idx / max(total, 1) * 100, 1),
        "stats": stats,
        "updated_at": datetime.utcnow().isoformat(),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",  type=int, default=0, help="Process at most N images (0=all)")
    parser.add_argument("--status", action="store_true", help="Show progress JSON and exit")
    args = parser.parse_args()

    if args.status:
        if PROGRESS.exists():
            print(PROGRESS.read_text())
        else:
            print("No progress file found — not started yet.")
        shots, flights = count_db_rows(DB_PATH)
        print(f"DB: {shots:,} screenshots, {flights:,} flights")
        return

    PID_PATH.write_text(str(os.getpid()))

    sys.path.insert(0, str(REPO))

    log("Phase 0 OCR — Full Pass")
    log(f"DB: {DB_PATH}")
    log("Scanning image files...")

    files  = build_file_list()
    target = len(files) if not args.limit else min(len(files), args.limit)
    log(f"Found {len(files):,} images total — processing {target:,}")

    # Import FlightAnalyzer AFTER file scan (avoids slow import on trivial ops)
    # FlightAnalyzer.__init__ → FlightDatabase.__init__ → _init_tables() creates correct schema
    log("Loading FlightAnalyzer + Tesseract (one-time startup)...")
    from pipeline.flight_analyzer import FlightAnalyzer
    analyzer = FlightAnalyzer(DATA_DIR, DB_PATH)
    log("Tesseract loaded and ready.")

    stats   = {"attempted": 0, "ocr_ok": 0, "skipped": 0, "errors": 0}
    t_start = time.time()

    for i, path in enumerate(files[:target]):
        idx = i + 1

        # Compute SHA-256 for dedup (same key used by FlightAnalyzer internally)
        try:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            sha256 = hashlib.sha256(path.name.encode()).hexdigest()

        # Skip images already in DB (from a previous run or partial pass)
        if already_processed(DB_PATH, sha256):
            stats["skipped"] += 1
        else:
            stats["attempted"] += 1
            try:
                # _process_single_image: hashes, dedup-checks, runs OCR, inserts row
                # Always returns None — success/failure is via exception
                analyzer._process_single_image(path)
                stats["ocr_ok"] += 1
            except Exception as exc:
                stats["errors"] += 1
                log(f"  ERR [{idx}] {path.name}: {exc}")

        # Progress log every 10 images
        if idx % 10 == 0 or idx == target:
            elapsed = time.time() - t_start
            rate    = elapsed / idx
            eta_min = (target - idx) * rate / 60
            shots, _ = count_db_rows(DB_PATH)
            log(f"  [{idx:>5}/{target}] {idx/target*100:.1f}%"
                f" | ok:{stats['ocr_ok']} skip:{stats['skipped']} err:{stats['errors']}"
                f" | {rate:.2f}s/img | DB:{shots:,} | ETA~{eta_min:.0f}min")
            save_progress(idx, target, stats)

    # Link screenshots → flights
    log("Linking screenshots → flights...")
    try:
        n_flights = analyzer.link_screenshots_to_flights()
        log(f"Flights linked: {n_flights}")
    except Exception as e:
        log(f"Warning: link_screenshots_to_flights: {e}")

    elapsed_total = time.time() - t_start
    shots, n_flights = count_db_rows(DB_PATH)
    save_progress(target, target, stats)

    log(f"\n{'='*55}")
    log(f"DONE — {elapsed_total/60:.1f} min total")
    log(f"  attempted:         {stats['attempted']:,}")
    log(f"  ocr_ok:            {stats['ocr_ok']:,}")
    log(f"  skipped (dedup):   {stats['skipped']:,}")
    log(f"  errors:            {stats['errors']:,}")
    log(f"  screenshots in DB: {shots:,}")
    log(f"  flights in DB:     {n_flights:,}")
    log(f"  DB: {DB_PATH}")
    log(f"{'='*55}")

    PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
