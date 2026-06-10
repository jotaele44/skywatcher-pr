"""
RLSM Phase 1 inventory.
- Walks data/FR24_baseline/**/*
- Populates SQLite screenshots table
- Computes perceptual hash (8x8 aHash, 64-bit hex)
- Assigns dup groups (exact via sha256, perceptual via phash Hamming <= 4)
- Emits outputs/rlsm_ingest_manifest.csv, rlsm_duplicate_report.csv, rlsm_failed_files.csv
- Resumable: skips screenshots already in the table

Run via:
    python3 scripts/rlsm_inventory.py [--budget-sec 35]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image

# HEIC support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # HEIC files will then be ingest_status='unreadable'


REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
BASELINE = REPO / "data" / "FR24_baseline"
MANIFEST_CSV = REPO / "data" / "_manifests" / "fr24_baseline" / "baseline_manifest.csv"
SCHEMA_SQL = REPO / "data" / "rlsm" / "schema.sql"
OUTPUTS = REPO / "outputs"

V1_PAT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})_([0-9a-f]{8})\.(png|jpg|jpeg|heic|webp)$",
    re.IGNORECASE,
)


def sha256_of(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ahash_8x8(img: Image.Image) -> str:
    """8×8 average-hash — returns 64-char hex string."""
    gray = img.convert("L").resize((8, 8), Image.LANCZOS)
    pixels = list(gray.getdata())
    avg = sum(pixels) / 64
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    h = int(bits, 2)
    return f"{h:016x}"


def hamming_distance(a: str, b: str) -> int:
    """Bit-level Hamming distance between two 64-bit hex phashes."""
    try:
        diff = int(a, 16) ^ int(b, 16)
        return bin(diff).count("1")
    except ValueError:
        return 64


def _parse_filename_ts(name: str):
    """Return ISO 8601 timestamp string if filename matches V1_PAT, else None."""
    m = V1_PAT.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist."""
    if SCHEMA_SQL.exists():
        conn.executescript(SCHEMA_SQL.read_text())
    conn.commit()


def _already_ingested(conn: sqlite3.Connection) -> set:
    """Return set of rel_paths already in the screenshots table."""
    rows = conn.execute("SELECT rel_path FROM screenshots").fetchall()
    return {r[0] for r in rows}


def _ingest_file(conn: sqlite3.Connection, path: Path, rel_path: str,
                 run_id: int) -> dict:
    """Insert one file into screenshots; return a result dict."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    name = path.name
    ext = path.suffix.lower().lstrip(".")

    # Filename-encoded timestamp
    fn_ts = _parse_filename_ts(name)

    # Month bucket from path (parent dir name like 2025-08)
    month_bucket = path.parent.name if re.match(r"^\d{4}-\d{2}$", path.parent.name) else None

    # File size
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        conn.execute(
            "INSERT INTO screenshots (sha256, filename, rel_path, month_bucket, filename_ts, ext, size_bytes, ingest_status, ingest_error, ingested_at) VALUES (?, ?, ?, ?, ?, ?, 0, 'unreadable', ?, ?)",
            (f"unknown_{name}", name, rel_path, month_bucket, fn_ts, ext, str(exc)[:200], ts),
        )
        conn.commit()
        return {"ok": False, "reason": "stat_error", "path": str(path)}

    # SHA-256
    try:
        sha = sha256_of(path)
    except OSError as exc:
        conn.execute(
            "INSERT INTO screenshots (sha256, filename, rel_path, month_bucket, filename_ts, ext, size_bytes, ingest_status, ingest_error, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'unreadable', ?, ?)",
            (f"unknown_{name}", name, rel_path, month_bucket, fn_ts, ext, size_bytes, str(exc)[:200], ts),
        )
        conn.commit()
        return {"ok": False, "reason": "read_error", "path": str(path)}

    # Check for exact-SHA duplicate before inserting
    existing = conn.execute(
        "SELECT screenshot_id FROM screenshots WHERE sha256=?", (sha,)
    ).fetchone()
    if existing:
        # Don't insert a full duplicate; caller handles dedup groups separately
        return {"ok": True, "dup_sha": sha, "existing_id": existing[0]}

    # Open image — width/height and phash
    width = height = None
    phash = None
    ingest_status = "ok"
    ingest_error = None
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            phash = ahash_8x8(img)
    except Exception as exc:
        ingest_status = "corrupt"
        ingest_error = f"{type(exc).__name__}: {exc}"[:200]

    try:
        conn.execute(
            """INSERT INTO screenshots
               (sha256, filename, rel_path, month_bucket, filename_ts, ext,
                size_bytes, width, height, phash,
                ingest_status, ingest_error, ocr_status, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (sha, name, rel_path, month_bucket, fn_ts, ext,
             size_bytes, width, height, phash,
             ingest_status, ingest_error, ts),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # SHA collision (extremely rare) — skip
        return {"ok": True, "dup_sha": sha}

    return {"ok": True, "sha": sha, "ingest_status": ingest_status}


def _assign_dup_groups(conn: sqlite3.Connection) -> int:
    """
    Assign dup_group_id for exact-SHA duplicates.
    Returns number of screenshots in any dup group.
    """
    rows = conn.execute(
        "SELECT sha256, COUNT(*) FROM screenshots GROUP BY sha256 HAVING COUNT(*) > 1"
    ).fetchall()
    if not rows:
        return 0
    group_id = (conn.execute("SELECT MAX(dup_group_id) FROM screenshots").fetchone()[0] or 0) + 1
    n_in_groups = 0
    for sha, cnt in rows:
        conn.execute(
            "UPDATE screenshots SET dup_group_id=? WHERE sha256=?",
            (group_id, sha),
        )
        group_id += 1
        n_in_groups += cnt
    conn.commit()
    return n_in_groups


def _assign_near_dup_groups(conn: sqlite3.Connection, hamming_thresh: int = 4) -> int:
    """
    Assign near_dup_group_id for screenshots with phash Hamming distance ≤ threshold.
    Simple O(n²) pass — acceptable for <15k images.
    Returns number of screenshots in any near-dup group.
    """
    rows = conn.execute(
        "SELECT screenshot_id, phash FROM screenshots WHERE phash IS NOT NULL AND near_dup_group_id IS NULL"
    ).fetchall()
    if not rows:
        return 0

    group_id = (conn.execute("SELECT MAX(near_dup_group_id) FROM screenshots").fetchone()[0] or 0) + 1
    id_to_group: dict = {}
    n_in_groups = 0

    for i in range(len(rows)):
        sid_a, ph_a = rows[i]
        if sid_a in id_to_group:
            continue
        cluster = [sid_a]
        for j in range(i + 1, len(rows)):
            sid_b, ph_b = rows[j]
            if sid_b in id_to_group:
                continue
            if hamming_distance(ph_a, ph_b) <= hamming_thresh:
                cluster.append(sid_b)
        if len(cluster) > 1:
            for sid in cluster:
                id_to_group[sid] = group_id
            conn.executemany(
                "UPDATE screenshots SET near_dup_group_id=? WHERE screenshot_id=?",
                [(group_id, sid) for sid in cluster],
            )
            group_id += 1
            n_in_groups += len(cluster)
    conn.commit()
    return n_in_groups


def _write_outputs(conn: sqlite3.Connection) -> None:
    """Write the three CSV artifacts to outputs/."""
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    # rlsm_ingest_manifest.csv — one row per screenshot
    rows = conn.execute(
        "SELECT screenshot_id, sha256, filename, rel_path, month_bucket, filename_ts, "
        "ext, size_bytes, width, height, phash, dup_group_id, near_dup_group_id, "
        "ingest_status, ingest_error, ocr_status, ingested_at FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    with open(OUTPUTS / "rlsm_ingest_manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["screenshot_id", "sha256", "filename", "rel_path", "month_bucket",
                    "filename_ts", "ext", "size_bytes", "width", "height", "phash",
                    "dup_group_id", "near_dup_group_id",
                    "ingest_status", "ingest_error", "ocr_status", "ingested_at"])
        w.writerows(rows)

    # rlsm_duplicate_report.csv — screenshots with dup_group_id
    dup_rows = conn.execute(
        "SELECT dup_group_id, sha256, GROUP_CONCAT(screenshot_id), GROUP_CONCAT(filename, '|') "
        "FROM screenshots WHERE dup_group_id IS NOT NULL "
        "GROUP BY dup_group_id ORDER BY dup_group_id"
    ).fetchall()
    with open(OUTPUTS / "rlsm_duplicate_report.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dup_group_id", "sha256", "screenshot_ids", "filenames"])
        w.writerows(dup_rows)

    # rlsm_failed_files.csv — corrupt / unreadable
    fail_rows = conn.execute(
        "SELECT screenshot_id, rel_path, ingest_status, ingest_error FROM screenshots "
        "WHERE ingest_status IN ('corrupt', 'unreadable') ORDER BY screenshot_id"
    ).fetchall()
    with open(OUTPUTS / "rlsm_failed_files.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["screenshot_id", "rel_path", "ingest_status", "ingest_error"])
        w.writerows(fail_rows)


def run(budget_sec: float) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    _ensure_schema(conn)

    # Register a new processing run
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) VALUES ('inventory', ?, 'in_progress', 0, 0, 0)",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),),
    )
    run_id = cur.lastrowid
    conn.commit()

    already = _already_ingested(conn)
    t0 = time.time()
    n_ok = n_fail = n_skip = 0

    for path in sorted(BASELINE.rglob("*")):
        if time.time() - t0 > budget_sec:
            break
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.suffix.lower() == ".json":
            continue
        rel = str(path.relative_to(REPO))
        if rel in already:
            n_skip += 1
            continue
        result = _ingest_file(conn, path, rel, run_id)
        if result.get("ok"):
            n_ok += 1
        else:
            n_fail += 1

    # Dedup groups
    _assign_dup_groups(conn)
    _assign_near_dup_groups(conn)
    _write_outputs(conn)

    elapsed = time.time() - t0
    conn.execute(
        "UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?, n_processed=?, n_failed=? WHERE run_id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), n_ok + n_fail, n_ok, n_fail, run_id),
    )
    conn.commit()
    conn.close()

    total = conn.execute("SELECT COUNT(*) FROM sqlite3.connect(DB_PATH)").fetchone() if False else None
    print(json.dumps({
        "run_id": run_id, "ingested": n_ok, "failed": n_fail, "skipped": n_skip,
        "elapsed_sec": round(elapsed, 2),
    }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 1: ingest FR24 baseline screenshots into SQLite.")
    ap.add_argument("--budget-sec", type=float, default=35.0,
                    help="Stop after this many seconds (resumable next run).")
    args = ap.parse_args()
    run(args.budget_sec)


if __name__ == "__main__":
    main()
