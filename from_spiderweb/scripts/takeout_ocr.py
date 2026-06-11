#!/usr/bin/env python3
"""
run_takeout_ocr.py  —  Google Photos Takeout → FR24 screenshots → pipeline DB

PHASE A  --extract  --archive PATH
    Streams the .tgz using indexed_gzip so every call continues where it left
    off in O(1) seek time (no re-reading from byte 0).  Extracts 1170×2532
    screenshots to STAGING_DIR.  Run repeatedly until checkpoint shows done.

PHASE B  --ocr
    Time-boxed (36 s) OCR of staged files → pipeline_full.db.  Run repeatedly.

UTILITY  --status   Show progress of both phases.
         --move-tmp  Move files from /tmp/takeout_staged into STAGING_DIR.
"""
import os
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse, hashlib, io, json, shutil, sqlite3, sys, tarfile, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
REPO        = Path("/sessions/beautiful-friendly-newton/mnt/spiderweb-pr")
DB_PATH     = Path("/tmp/pipeline_full.db")
SESSIONS    = Path("/sessions/beautiful-friendly-newton/mnt")
# STAGING_DIR is /tmp so files can be deleted (virtiofs mount blocks unlink)
STAGING_DIR = Path("/tmp/takeout_staged")
INDEX_DIR   = SESSIONS / "outputs"          # gzip index lives here
EXTRACT_CKPT= Path("/tmp/takeout_extract_ckpt.json")
OCR_CKPT    = Path("/tmp/takeout_ocr_ckpt.json")
LOG_PATH    = Path("/tmp/takeout_extract.log")

# ── constants ──────────────────────────────────────────────────────────────────
TARGET_W, TARGET_H = 1170, 2532
GZ_SPACING  = 10 * 1024 * 1024   # gzip index point every 10 MB uncompressed
TIME_BUDGET = 36                  # seconds per extract OR ocr call
N_WORKERS   = 4
SUPPORTED   = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
_db_lock    = threading.Lock()


# ── logging ───────────────────────────────────────────────────────────────────
def _log(msg: str):
    ts   = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ── checkpoint helpers ─────────────────────────────────────────────────────────
def _load_extract_ckpt(archive_path: str) -> dict:
    if EXTRACT_CKPT.exists():
        cp = json.loads(EXTRACT_CKPT.read_text())
        if cp.get("archive") == archive_path:
            return cp
    return {
        "archive":              archive_path,
        "member_offset":        0,    # uncompressed byte offset of LAST processed header
        "members_scanned":      0,
        "staged":               0,
        "done":                 False,
    }

def _save_extract_ckpt(cp: dict):
    EXTRACT_CKPT.write_text(json.dumps(cp, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE A — extract
# ══════════════════════════════════════════════════════════════════════════════

def run_extract(archive_path: str):
    import indexed_gzip
    from PIL import Image

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cp = _load_extract_ckpt(archive_path)

    if cp["done"]:
        _log(f"Extract already complete ({cp['staged']} staged).  Run --ocr.")
        return

    index_file = INDEX_DIR / (Path(archive_path).name + ".gzidx")
    resume_offset = cp["member_offset"]

    _log(f"=== EXTRACT  archive={Path(archive_path).name}")
    _log(f"    resume offset={resume_offset:,}  scanned={cp['members_scanned']:,}  staged={cp['staged']:,}")

    staged_this_call = 0
    scanned_this_call = 0
    t_start = time.time()
    last_member_offset = resume_offset

    try:
        igz = indexed_gzip.IndexedGzipFile(archive_path, mode="rb", spacing=GZ_SPACING)

        # Import existing index (enables O(1) seek)
        if index_file.exists():
            _log(f"    Importing index ({index_file.stat().st_size // 1024**2} MB)…")
            igz.import_index(str(index_file))
            _log(f"    Index imported in {time.time()-t_start:.1f}s")

        # Seek to last processed member
        if resume_offset > 0:
            _log(f"    Seeking to {resume_offset:,}…")
            igz.seek(resume_offset)
            _log(f"    Seek done in {time.time()-t_start:.1f}s")

        # Open streaming tarfile at current igz position
        tf = tarfile.open(fileobj=igz, mode="r|")

        # If resuming, skip the member AT resume_offset (already processed)
        first_member = True

        for member in tf:
            elapsed = time.time() - t_start
            # member.offset is RELATIVE to where tarfile was opened (i.e., relative to
            # resume_offset).  Convert to absolute uncompressed position.
            abs_offset = resume_offset + member.offset

            if elapsed >= TIME_BUDGET:
                last_member_offset = abs_offset
                break

            if first_member and resume_offset > 0:
                # Header at resume_offset — already processed last call, skip it
                first_member = False
                continue
            first_member = False

            scanned_this_call += 1
            last_member_offset = abs_offset   # advance checkpoint each member

            if not member.isfile():
                continue
            ext = Path(member.name).suffix.lower()
            if ext not in SUPPORTED:
                continue

            try:
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                raw = fobj.read()
                w, h = Image.open(io.BytesIO(raw)).size
                if w == TARGET_W and h == TARGET_H:
                    sha256 = hashlib.sha256(raw).hexdigest()
                    dest   = STAGING_DIR / f"{sha256}.png"
                    if not dest.exists():
                        dest.write_bytes(raw)
                    staged_this_call += 1
            except Exception as ex:
                _log(f"    WARN {member.name}: {ex}")

            if scanned_this_call % 200 == 0:
                elapsed = time.time() - t_start
                rate    = scanned_this_call / elapsed if elapsed else 0
                _log(f"    scanned:{cp['members_scanned']+scanned_this_call:,}"
                     f"  staged:{cp['staged']+staged_this_call}"
                     f"  {rate:.1f}/s  offset:{last_member_offset:,}")
        else:
            # Loop exhausted normally → archive fully scanned
            cp["done"] = True

        # Export updated index (covers all data read so far)
        _log(f"    Exporting gzip index…")
        igz.export_index(str(index_file))
        igz.close()

    except Exception as ex:
        import traceback
        _log(f"ERROR: {ex}")
        _log(traceback.format_exc())

    # Update checkpoint
    cp["member_offset"]   = last_member_offset
    cp["members_scanned"] += scanned_this_call
    cp["staged"]          += staged_this_call
    _save_extract_ckpt(cp)

    elapsed = time.time() - t_start
    total_staged = len(list(STAGING_DIR.glob("*.png")))
    _log(f"    +{scanned_this_call} scanned  +{staged_this_call} staged  {elapsed:.1f}s")
    _log(f"    total staged on disk: {total_staged}  checkpoint offset: {last_member_offset:,}")
    if cp["done"]:
        _log(f"=== EXTRACT COMPLETE: {cp['staged']} total staged")
    else:
        _log(f"    Run again to continue ({archive_path})")


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE B — OCR
# ══════════════════════════════════════════════════════════════════════════════

def _ocr_one(path_str: str, db_path_str: str, ocr_obj) -> dict:
    path = Path(path_str)
    try:
        raw    = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
    except OSError as e:
        return {"status": "err", "path": path_str, "err": str(e)}

    conn = sqlite3.connect(db_path_str, check_same_thread=False)
    row  = conn.execute(
        "SELECT 1 FROM screenshots WHERE screenshot_id=?", (sha256,)
    ).fetchone()
    conn.close()
    if row:
        return {"status": "skip", "path": path_str}

    try:
        data = ocr_obj.extract_from_image(path_str)
    except Exception as e:
        return {"status": "err", "path": path_str, "sha256": sha256, "err": str(e)}

    return {"status": "ok", "path": path_str, "sha256": sha256, "data": data}


def run_ocr(delete_after: bool = False):
    if not STAGING_DIR.exists():
        print("  Staging dir not found — run --extract first.")
        return

    staged_files = sorted(STAGING_DIR.glob("*.png"))
    total = len(staged_files)
    if total == 0:
        print("  No staged files — run --extract first.")
        return

    cp = {"processed_idx": 0, "stats": {"ok": 0, "skip": 0, "err": 0},
          "total_ok": 0, "total_skip": 0, "total_err": 0}
    if OCR_CKPT.exists():
        cp = json.loads(OCR_CKPT.read_text())
        # backfill total fields from older checkpoints
        if "total_ok" not in cp:
            cp["total_ok"]    = cp["stats"]["ok"]
            cp["total_skip"]  = cp["stats"]["skip"]
            cp["total_err"]   = cp["stats"]["err"]

    start_idx = cp["processed_idx"]
    if start_idx >= total:
        # All files from the previous batch are processed — reset for new batch
        print(f"  Batch reset: {total} new staged files, starting fresh batch.")
        start_idx = 0
        cp["processed_idx"] = 0
        cp["stats"] = {"ok": 0, "skip": 0, "err": 0}

    sys.path.insert(0, str(REPO))
    from pipeline.flight_analyzer import FlightAnalyzer
    fa = FlightAnalyzer(STAGING_DIR, DB_PATH)

    ok = skip = err = 0
    t_start = time.time()
    idx     = start_idx

    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        while idx < total:
            if time.time() - t_start >= TIME_BUDGET:
                break
            mini_end = min(idx + N_WORKERS, total)
            mini     = [str(staged_files[i]) for i in range(idx, mini_end)]
            futs     = {ex.submit(_ocr_one, p, str(DB_PATH), fa.ocr): p for p in mini}
            for fut in as_completed(futs):
                r = fut.result()
                if r["status"] == "ok":
                    with _db_lock:
                        try:
                            fa.db.store_screenshot(r["sha256"], r["path"], r["data"])
                            if delete_after:
                                Path(r["path"]).unlink(missing_ok=True)
                        except Exception as e:
                            print(f"  DB err: {e}", file=sys.stderr)
                    ok += 1
                elif r["status"] == "skip":
                    if delete_after:
                        Path(r["path"]).unlink(missing_ok=True)
                    skip += 1
                else:
                    err += 1
            idx = mini_end

    elapsed  = time.time() - t_start
    done     = idx - start_idx
    cp["processed_idx"]     = idx
    cp["stats"]["ok"]      += ok
    cp["stats"]["skip"]    += skip
    cp["stats"]["err"]     += err
    cp["total_ok"]         += ok
    cp["total_skip"]       += skip
    cp["total_err"]        += err
    OCR_CKPT.write_text(json.dumps(cp, indent=2))

    pct  = idx / total * 100
    rate = done / elapsed if elapsed else 0
    total_ok = cp["total_ok"]; total_skip = cp["total_skip"]
    print(f"  [{idx}/{total}]  {pct:.1f}%  +{done} imgs  {elapsed:.1f}s  ({rate:.2f}/s)")
    print(f"  batch  ok:{ok}  skip:{skip}  err:{err}")
    print(f"  cumul  ok:{total_ok}  skip:{total_skip}")
    if idx < total:
        print(f"  {total-idx} remaining — run again")


# ══════════════════════════════════════════════════════════════════════════════
#  STATUS
# ══════════════════════════════════════════════════════════════════════════════

def show_status():
    print("\n══════════════ TAKEOUT OCR STATUS ══════════════")
    if EXTRACT_CKPT.exists():
        ep  = json.loads(EXTRACT_CKPT.read_text())
        tag = "DONE" if ep.get("done") else "in-progress"
        print(f"  Extract  : {tag}")
        print(f"             archive  = {ep.get('archive','?')}")
        print(f"             scanned  = {ep.get('members_scanned',0):,}")
        print(f"             staged   = {ep.get('staged',0):,}")
        print(f"             offset   = {ep.get('member_offset',0):,}")
    else:
        print("  Extract  : not started")

    staged_files = list(STAGING_DIR.glob("*.png")) if STAGING_DIR.exists() else []
    staged_mb    = sum(f.stat().st_size for f in staged_files) / 1024**2
    print(f"  Staged   : {len(staged_files):,} files  ({staged_mb:.0f} MB)")

    if OCR_CKPT.exists():
        op = json.loads(OCR_CKPT.read_text())
        s  = op["stats"]
        print(f"  OCR      : {op['processed_idx']:,}/{len(staged_files)}  "
              f"ok:{s['ok']}  skip:{s['skip']}  err:{s['err']}")
    else:
        print("  OCR      : not started")

    if DB_PATH.exists():
        conn    = sqlite3.connect(str(DB_PATH))
        shots   = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
        flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        conn.close()
        print(f"  DB       : {shots:,} screenshots  {flights:,} flights")

    # index files
    for idx_f in INDEX_DIR.glob("*.gzidx"):
        sz = idx_f.stat().st_size / 1024**2
        print(f"  GZ index : {idx_f.name}  ({sz:.0f} MB)")

    if LOG_PATH.exists():
        lines  = [l for l in LOG_PATH.read_text().split('\n') if l.strip()][-8:]
        print("\n  Recent log:")
        for l in lines:
            print(f"    {l}")
    print("═" * 48)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract",   action="store_true")
    ap.add_argument("--archive",   help="Path to .tgz (required for --extract)")
    ap.add_argument("--ocr",       action="store_true")
    ap.add_argument("--delete",    action="store_true",
                    help="Delete staged files after successful OCR (saves disk)")
    ap.add_argument("--status",    action="store_true")
    ap.add_argument("--move-tmp",  action="store_true",
                    help="Move files from /tmp/takeout_staged to STAGING_DIR")
    ap.add_argument("--reset",     action="store_true",
                    help="Clear extract + ocr checkpoints")
    args = ap.parse_args()

    if args.reset:
        for f in [EXTRACT_CKPT, OCR_CKPT]:
            if f.exists():
                f.unlink()
        print("  Checkpoints cleared.")

    elif args.move_tmp:
        src = Path("/tmp/takeout_staged")
        if not src.exists():
            print("  /tmp/takeout_staged not found")
            return
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in src.glob("*.png"):
            dest = STAGING_DIR / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                moved += 1
        print(f"  Moved {moved} files to {STAGING_DIR}")

    elif args.status:
        show_status()

    elif args.extract:
        if not args.archive:
            print("ERROR: --archive PATH required"); sys.exit(1)
        if not Path(args.archive).exists():
            print(f"ERROR: archive not found: {args.archive}"); sys.exit(1)
        run_extract(args.archive)

    elif args.ocr:
        run_ocr(delete_after=args.delete)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
