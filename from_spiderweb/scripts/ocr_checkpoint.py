#!/usr/bin/env python3
"""
Full Phase 0 OCR Checkpoint Runner
Processes all Flight Logs subdirectories through FlightAnalyzer (Tesseract OCR).
Runs in small batches to stay within 45-second bash call limits.
Run repeatedly until DONE is printed.

Usage:
  python run_ocr_checkpoint.py [--batch N] [--reset] [--status]

Defaults:
  --batch 11   (≈11 images × ~3.5s = ~38s per call)
  DB stored at /tmp/pipeline_full.db  (virtiofs WAL workaround)
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO       = Path(__file__).parent
DATA_DIR   = REPO / "data" / "Flight Logs"
DB_PATH    = Path("/tmp/pipeline_full.db")
CHECKPOINT = Path("/tmp/ocr_checkpoint.json")

# Supported by FlightAnalyzer (no HEIC)
SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}

BATCH = 11   # images per bash call — keeps wall time < 42s


# ── checkpoint I/O ───────────────────────────────────────────────────────────

def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {
        "processed_idx": 0,
        "total_files": 0,
        "file_list": [],      # list of absolute path strings (built once)
        "stats": {
            "attempted": 0, "ocr_ok": 0, "ocr_skip": 0, "ocr_err": 0,
            "flights_linked": 0,
        },
        "started_at": datetime.utcnow().isoformat(),
    }


def save_checkpoint(cp):
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(cp, indent=2))


# ── helpers ──────────────────────────────────────────────────────────────────

def build_file_list() -> list[str]:
    """Collect all non-HEIC images across monthly subdirs, sorted."""
    paths = []
    for sub in sorted(DATA_DIR.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.iterdir()):
            if p.suffix.lower() in SUPPORTED:
                paths.append(str(p))
    return paths


def count_db_rows(db_path: Path):
    if not db_path.exists():
        return 0, 0
    conn = sqlite3.connect(str(db_path))
    shots = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
    try:
        flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    except Exception:
        flights = 0
    conn.close()
    return shots, flights


# ── core OCR batch ────────────────────────────────────────────────────────────

def run_ocr_batch(file_paths: list[str], db_path: Path) -> dict:
    """
    Run FlightAnalyzer on each file individually.
    FlightAnalyzer.process_all_images() uses iterdir() (flat scan),
    so we monkey-patch it to accept an explicit file list instead.
    """
    sys.path.insert(0, str(REPO))
    from pipeline.flight_analyzer import FlightAnalyzer

    # We need a per-file approach since FlightAnalyzer iterdir()s a directory.
    # Workaround: process each monthly batch by pointing at its parent dir,
    # but we'll override the internal file list.

    stats = {"attempted": 0, "ocr_ok": 0, "ocr_skip": 0, "ocr_err": 0}

    analyzer = FlightAnalyzer(DATA_DIR, db_path)

    for path_str in file_paths:
        p = Path(path_str)
        stats["attempted"] += 1
        try:
            result = analyzer._process_single_image(p)
            if result is None:
                stats["ocr_skip"] += 1
            else:
                stats["ocr_ok"] += 1
        except Exception as exc:
            stats["ocr_err"] += 1
            # Non-fatal — log and continue
            print(f"    ERR {p.name}: {exc}", file=sys.stderr)

    return stats


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch",  type=int, default=BATCH)
    parser.add_argument("--reset",  action="store_true", help="Clear checkpoint and restart")
    parser.add_argument("--status", action="store_true", help="Show progress and exit")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.reset:
        for f in [CHECKPOINT, DB_PATH]:
            if f.exists():
                f.unlink()
        print("  Checkpoint cleared — starting fresh")

    cp = load_checkpoint()

    # Build file list once and cache it in the checkpoint
    if not cp["file_list"]:
        file_list = build_file_list()
        cp["file_list"]   = file_list
        cp["total_files"] = len(file_list)
        save_checkpoint(cp)
        print(f"  Discovered {len(file_list):,} images across monthly folders")
    else:
        file_list = cp["file_list"]

    shots_in_db, flights_in_db = count_db_rows(DB_PATH)

    if args.status:
        pct = cp["processed_idx"] / max(cp["total_files"], 1) * 100
        print(f"\n  OCR Status:")
        print(f"    Files processed:  {cp['processed_idx']:>6,} / {cp['total_files']:,}  ({pct:.1f}%)")
        print(f"    OCR ok / skip / err: {cp['stats']['ocr_ok']:,} / {cp['stats']['ocr_skip']:,} / {cp['stats']['ocr_err']:,}")
        print(f"    Screenshots in DB:   {shots_in_db:,}")
        print(f"    Flights linked:      {flights_in_db:,}")
        return

    start_idx = cp["processed_idx"]
    end_idx   = min(start_idx + args.batch, len(file_list))
    batch     = file_list[start_idx:end_idx]

    # ── DONE ─────────────────────────────────────────────────────────────────
    if not batch:
        s = cp["stats"]
        shots_in_db, flights_in_db = count_db_rows(DB_PATH)
        print(f"\n{'='*60}")
        print("  DONE — all images processed through OCR")
        print(f"  Total attempted:   {s['attempted']:>8,}")
        print(f"  OCR ok:            {s['ocr_ok']:>8,}")
        print(f"  Skipped (dupes):   {s['ocr_skip']:>8,}")
        print(f"  Errors:            {s['ocr_err']:>8,}")
        print(f"  Screenshots in DB: {shots_in_db:>8,}")
        print(f"  Flights in DB:     {flights_in_db:>8,}")
        print(f"  DB:                {DB_PATH}")
        print(f"{'='*60}")
        return

    print(f"\n  PHASE 0 OCR — batch {start_idx+1}–{end_idx} of {len(file_list):,}")
    print(f"  {'─'*55}")

    # Ensure schema exists — FlightAnalyzer.__init__ calls _init_tables() via FlightDatabase
    from pipeline.flight_analyzer import FlightAnalyzer
    _init = FlightAnalyzer(DATA_DIR, DB_PATH)   # triggers schema creation
    del _init

    t0 = time.time()
    batch_stats = run_ocr_batch(batch, DB_PATH)
    elapsed = time.time() - t0

    # Link screenshots → flights after every batch
    flights_linked = 0
    try:
        analyzer2 = FlightAnalyzer(DATA_DIR, DB_PATH)
        flights_linked = analyzer2.link_screenshots_to_flights()
        analyzer2.conn.close()
    except Exception as e:
        print(f"  Warning: link_screenshots_to_flights failed: {e}", file=sys.stderr)

    # Update checkpoint
    cp["processed_idx"] = end_idx
    for k in ("attempted", "ocr_ok", "ocr_skip", "ocr_err"):
        cp["stats"][k] += batch_stats[k]
    cp["stats"]["flights_linked"] = flights_linked
    save_checkpoint(cp)

    shots_in_db, flights_in_db = count_db_rows(DB_PATH)
    pct       = end_idx / len(file_list) * 100
    remaining = len(file_list) - end_idx
    rate      = elapsed / len(batch) if batch else 0
    eta_min   = remaining * rate / 60

    print(f"  Batch done in {elapsed:.1f}s  ({rate:.2f}s/img)")
    print(f"  Progress:  {end_idx:,} / {len(file_list):,}  ({pct:.1f}%)")
    print(f"  This batch → ok:{batch_stats['ocr_ok']}  skip:{batch_stats['ocr_skip']}  err:{batch_stats['ocr_err']}")
    print(f"  DB → screenshots:{shots_in_db:,}  flights:{flights_in_db:,}")
    print(f"  ETA: ~{eta_min:.0f} min remaining")
    if end_idx >= len(file_list):
        print(f"\n  ALL FILES PROCESSED ✓  Run once more to see final summary.")
    else:
        print(f"\n  Run again to continue from image {end_idx+1:,}")


if __name__ == "__main__":
    main()
