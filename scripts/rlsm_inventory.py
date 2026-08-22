#!/usr/bin/env python3
"""Compatibility entry point for the provenance-first RLSM corpus freeze.

The production command delegates to :mod:`fr24.rlsm_corpus_ingest`.  A small
legacy API is retained for callers that import ``_ingest_file`` or
``_write_outputs`` directly.  Those adapters are deliberately not used by the
production corpus-freeze command and therefore cannot reinstate the former
SHA-collapsing inventory workflow.
"""
from __future__ import annotations

import csv
import hashlib
import importlib
import sqlite3
import sys
import time
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
OUTPUTS = REPO / "outputs"
sys.path.insert(0, str(REPO))


def _sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_ahash(image: Image.Image) -> str:
    gray = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    average = sum(pixels) / max(1, len(pixels))
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _ingest_file(
    conn: sqlite3.Connection,
    path: Path,
    rel_path: str,
    run_id: int,
) -> dict:
    """Deprecated single-file adapter preserved for compatibility tests/callers.

    This is not the production corpus denominator.  It writes one historical
    logical screenshot row with explicit source availability and refuses to
    invent bytes when the source cannot be read.
    """
    del run_id  # retained in the signature for historical callers
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        size_bytes = path.stat().st_size
        sha256 = _sha256_file(path)
    except OSError as exc:
        return {"ok": False, "reason": type(exc).__name__, "error": str(exc)}

    existing = conn.execute(
        "SELECT screenshot_id FROM screenshots WHERE sha256=?", (sha256,)
    ).fetchone()
    if existing:
        return {"ok": True, "dup_sha": sha256, "existing_id": int(existing[0])}

    width = height = None
    phash = None
    ingest_status = "ok"
    ingest_error = None
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            phash = _legacy_ahash(image)
    except Exception as exc:  # decoding failure is retained as evidence
        ingest_status = "corrupt"
        ingest_error = f"{type(exc).__name__}: {exc}"[:400]

    month_bucket = path.parent.name if len(path.parent.name) == 7 else None
    try:
        conn.execute(
            """INSERT INTO screenshots
               (sha256, filename, rel_path, month_bucket, filename_ts, ext,
                size_bytes, width, height, phash, ingest_status, ingest_error,
                ocr_status, source_availability, availability_checked_at,
                availability_detail, availability_source, ingested_at)
               VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'pending',
                       'present', ?, 'legacy_compat_ingest', 'inventory', ?)""",
            (
                sha256,
                path.name,
                rel_path,
                month_bucket,
                path.suffix.lower().lstrip("."),
                size_bytes,
                width,
                height,
                phash,
                ingest_status,
                ingest_error,
                now,
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        return {"ok": False, "reason": "integrity_error", "error": str(exc)}
    return {"ok": True, "sha": sha256, "ingest_status": ingest_status}


def _write_outputs(conn: sqlite3.Connection) -> None:
    """Deprecated compatibility export; production uses corpus-freeze artifacts."""
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    fields = [
        "screenshot_id",
        "sha256",
        "filename",
        "rel_path",
        "month_bucket",
        "filename_ts",
        "ext",
        "size_bytes",
        "width",
        "height",
        "phash",
        "dup_group_id",
        "near_dup_group_id",
        "ingest_status",
        "ingest_error",
        "ocr_status",
        "source_availability",
        "availability_checked_at",
        "availability_detail",
        "availability_source",
        "ingested_at",
    ]
    rows = conn.execute(
        """SELECT screenshot_id, sha256, filename, rel_path, month_bucket,
                  filename_ts, ext, size_bytes, width, height, phash,
                  dup_group_id, near_dup_group_id, ingest_status, ingest_error,
                  ocr_status, source_availability, availability_checked_at,
                  availability_detail, availability_source, ingested_at
           FROM screenshots ORDER BY screenshot_id"""
    ).fetchall()
    with (OUTPUTS / "rlsm_ingest_manifest.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def main() -> int:
    """Run the controlling provenance-first corpus freeze."""
    module = importlib.import_module("fr24.rlsm_corpus_ingest")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
