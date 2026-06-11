#!/usr/bin/env python3
"""
Phase 0 OCR — Parallel checkpoint runner.
4 Tesseract workers with OMP_THREAD_LIMIT=1 → ~1.1s/img effective.
Time-based exit: processes images until 38s elapsed, saves checkpoint, exits.
Run repeatedly until DONE.

Usage:
  python3 run_ocr_parallel.py            # process one ~38s time-box
  python3 run_ocr_parallel.py --status   # show progress without processing
  python3 run_ocr_parallel.py --reset    # clear checkpoint and DB, restart

Expected throughput: ~35 images / 42s call → ~183 calls for 6,407 images.
"""
import os
# Must set before any Tesseract/pytesseract import
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO      = Path(__file__).parent
DATA_DIR  = REPO / "data" / "Flight Logs"
DB_PATH   = Path("/tmp/pipeline_full.db")
CKPT_PATH = Path("/tmp/ocr_parallel_checkpoint.json")

SUPPORTED    = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
N_WORKERS    = 4
TIME_BUDGET  = 28    # seconds; exit gracefully before 44s bash timeout
MINI_BATCH   = N_WORKERS   # images submitted per round to the thread pool

_db_lock = threading.Lock()


# ── Checkpoint ────────────────────────────────────────────────────────────────

def load_ckpt():
    if CKPT_PATH.exists():
        return json.loads(CKPT_PATH.read_text())
    return {"processed_idx": 0, "total": 0, "file_list": [],
            "stats": {"ok": 0, "skip": 0, "err": 0},
            "started_at": datetime.utcnow().isoformat()}

def save_ckpt(cp):
    CKPT_PATH.write_text(json.dumps(cp, indent=2))


# ── File discovery ────────────────────────────────────────────────────────────

def build_file_list() -> list[str]:
    paths = []
    for sub in sorted(DATA_DIR.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.iterdir()):
            if p.suffix.lower() in SUPPORTED:
                paths.append(str(p))
    return paths


# ── OCR worker (runs in thread) ───────────────────────────────────────────────

def ocr_one(path_str: str, db_path_str: str, ocr) -> dict:
    """Hash, dedup-check, run OCR. Thread-safe (read-only DB access)."""
    path = Path(path_str)
    try:
        raw    = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
    except OSError as e:
        return {"status": "err", "path": path_str, "err": str(e)}

    # Dedup check (read-only connection, safe from threads)
    conn = sqlite3.connect(db_path_str, check_same_thread=False)
    row  = conn.execute(
        "SELECT 1 FROM screenshots WHERE screenshot_id = ?", (sha256,)
    ).fetchone()
    conn.close()
    if row:
        return {"status": "skip", "path": path_str}

    # OCR
    try:
        data = ocr.extract_from_image(path_str)
    except Exception as e:
        return {"status": "err", "path": path_str, "sha256": sha256, "err": str(e)}

    # Aircraft position (optional)
    try:
        from PIL import Image
        from pipeline.flight_analyzer import CoordinateMapper
        img  = Image.open(path_str)
        w, h = img.size
        mapper = CoordinateMapper(w, h)
        lat, lon = mapper.detect_aircraft_position(path_str)
        if lat != 0.0 and lon != 0.0:
            data.latitude  = lat
            data.longitude = lon
    except Exception:
        pass

    return {"status": "ok", "path": path_str, "sha256": sha256, "data": data}


# ── DB write (thread-safe via lock) ───────────────────────────────────────────

def db_write(result: dict, db_obj):
    if result["status"] != "ok":
        return
    with _db_lock:
        try:
            db_obj.store_screenshot(result["sha256"], result["path"], result["data"])
        except Exception as e:
            print(f"  DB write err {Path(result['path']).name}: {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset",  action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.reset:
        for f in [CKPT_PATH, DB_PATH]:
            if f.exists():
                f.unlink()
        print("  Checkpoint and DB cleared.")

    cp = load_ckpt()

    # Build file list once and cache in checkpoint
    if not cp["file_list"]:
        fl = build_file_list()
        cp["file_list"] = fl
        cp["total"]     = len(fl)
        save_ckpt(cp)
        print(f"  Discovered {len(fl):,} images.", flush=True)

    file_list = cp["file_list"]
    total     = cp["total"]

    # ── Status ────────────────────────────────────────────────────────────────
    if args.status:
        idx = cp["processed_idx"]
        s   = cp["stats"]
        pct = idx / max(total, 1) * 100
        shots = flights = 0
        if DB_PATH.exists():
            conn   = sqlite3.connect(str(DB_PATH))
            shots  = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
            flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
            conn.close()
        print(f"\n  Progress:  {idx:,} / {total:,}  ({pct:.1f}%)")
        print(f"  ok:{s['ok']:,}  skip:{s['skip']:,}  err:{s['err']:,}")
        print(f"  DB → screenshots:{shots:,}  flights:{flights:,}")
        eta_s = (total - idx) * 1.1   # ~1.1s/img effective
        print(f"  ETA: ~{eta_s/60:.0f} min at {N_WORKERS} workers (OMP=1)")
        return

    # ── Done? ─────────────────────────────────────────────────────────────────
    if cp["processed_idx"] >= total:
        s = cp["stats"]
        shots = flights = 0
        if DB_PATH.exists():
            conn   = sqlite3.connect(str(DB_PATH))
            shots  = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
            flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
            conn.close()
        print(f"\n{'='*55}")
        print(f"  DONE — all {total:,} images processed")
        print(f"  ok:{s['ok']:,}  skip:{s['skip']:,}  err:{s['err']:,}")
        print(f"  DB → screenshots:{shots:,}  flights:{flights:,}")
        print(f"{'='*55}")
        return

    # ── Import (after status/done checks to keep those fast) ─────────────────
    sys.path.insert(0, str(REPO))
    from pipeline.flight_analyzer import FlightAnalyzer
    fa  = FlightAnalyzer(DATA_DIR, DB_PATH)   # creates schema
    ocr = fa.ocr

    # ── Time-boxed processing ─────────────────────────────────────────────────
    start_idx = cp["processed_idx"]
    idx       = start_idx
    ok = skip = err = 0
    t_start   = time.time()

    with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
        while idx < total:
            elapsed = time.time() - t_start
            if elapsed >= TIME_BUDGET:
                break

            # Submit a mini-batch of MINI_BATCH images
            mini_end = min(idx + MINI_BATCH, total)
            mini     = file_list[idx:mini_end]

            futures = {
                executor.submit(ocr_one, p, str(DB_PATH), ocr): p
                for p in mini
            }
            for future in as_completed(futures):
                result = future.result()
                if result["status"] == "ok":
                    db_write(result, fa.db)
                    ok   += 1
                elif result["status"] == "skip":
                    skip += 1
                else:
                    err += 1
                    print(f"  ERR {Path(result['path']).name}: {result.get('err','?')}",
                          file=sys.stderr, flush=True)

            idx = mini_end

    elapsed = time.time() - t_start
    done    = idx - start_idx
    rate    = elapsed / done if done else 0

    # Update checkpoint
    cp["processed_idx"]  = idx
    cp["stats"]["ok"]   += ok
    cp["stats"]["skip"] += skip
    cp["stats"]["err"]  += err
    save_ckpt(cp)

    shots = flights = 0
    if DB_PATH.exists():
        conn    = sqlite3.connect(str(DB_PATH))
        shots   = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
        flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        conn.close()

    remaining = total - idx
    eta_min   = remaining * rate / 60

    pct = idx / total * 100
    print(f"  [{idx:>5}/{total}] {pct:.1f}%  +{done} imgs in {elapsed:.1f}s ({rate:.2f}s/img eff)")
    print(f"  ok:{ok}  skip:{skip}  err:{err}  |  DB:{shots:,} screenshots  {flights:,} flights")
    print(f"  ETA ~{eta_min:.0f} min  |  run again to continue", flush=True)


if __name__ == "__main__":
    main()
