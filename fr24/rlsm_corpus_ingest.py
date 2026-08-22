"""Provenance-first RLSM screenshot corpus freeze.

This module separates logical screenshot payload identity from source
manifestation identity.  ``screenshots`` remains the stable, downstream-facing
logical payload table (one row per SHA-256), while every pathname/archive member
is preserved as a source manifestation/observation.

The freeze is deliberately fail-closed: a budget-limited traversal, unreadable
bytes, pathname/hash contradiction, archive scan failure, or arithmetic mismatch
cannot produce PASS.  No OCR is performed here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import tarfile
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from PIL import Image

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
BASELINE = REPO / "data" / "FR24_baseline"
SCHEMA_SQL = REPO / "data" / "rlsm" / "schema.sql"
OUTPUT_DIR = REPO / "outputs" / "rlsm_corpus"
DEFAULT_ARCHIVE_ROOTS = (
    REPO / "data" / "FR24_archives",
    REPO / "data" / "screenshot_archives",
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
ARCHIVE_SUFFIXES = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
)
CORPUS_PROTOCOL = "rlsm-corpus-freeze-v1.0"
OCR_GATE = "RLSM_OCR_CALIBRATION"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_stream(handle: BinaryIO, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    while True:
        block = handle.read(chunk)
        if not block:
            return digest.hexdigest()
        digest.update(block)


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle)


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_archive(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _locator(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(repo_root.resolve()))
    except ValueError:
        return "external:" + str(resolved)


def _filename_ts(name: str) -> str | None:
    # Import the canonical parser rather than carrying a second filename grammar.
    from src.skywatcher.fr24.screenshot_metadata import parse_filename_timestamp

    return parse_filename_timestamp(name)


def _month_bucket(path: Path) -> str | None:
    parent = path.parent.name
    if len(parent) == 7 and parent[4] == "-" and parent[:4].isdigit() and parent[5:].isdigit():
        return parent
    return None


def _ahash_8x8(img: Image.Image) -> str:
    gray = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    avg = sum(pixels) / 64
    return f"{int(''.join('1' if p >= avg else '0' for p in pixels), 2):016x}"


def ensure_base_schema(conn: sqlite3.Connection, schema_sql: Path = SCHEMA_SQL) -> None:
    if schema_sql.exists():
        conn.executescript(schema_sql.read_text(encoding="utf-8"))
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screenshots'"
    ).fetchone():
        raise RuntimeError("RLSM screenshots schema is unavailable")
    conn.commit()


def ensure_corpus_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS corpus_freeze_runs (
            corpus_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('IN_PROGRESS','PASS','FAIL','OPEN_PARTIAL')),
            baseline_root TEXT NOT NULL,
            archive_roots_json TEXT NOT NULL,
            corpus_digest TEXT,
            counts_json TEXT,
            certification_json TEXT
        );

        CREATE TABLE IF NOT EXISTS source_manifestations (
            manifestation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL CHECK(source_kind IN ('baseline_file','historical_db_path')),
            rel_path TEXT NOT NULL,
            screenshot_id INTEGER REFERENCES screenshots(screenshot_id),
            first_seen_at TEXT NOT NULL,
            UNIQUE(source_kind, rel_path)
        );
        CREATE INDEX IF NOT EXISTS ix_source_manifestations_screenshot
            ON source_manifestations(screenshot_id);

        CREATE TABLE IF NOT EXISTS source_manifestation_observations (
            manifestation_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_run_id INTEGER NOT NULL REFERENCES corpus_freeze_runs(corpus_run_id),
            manifestation_id INTEGER NOT NULL REFERENCES source_manifestations(manifestation_id),
            observed_sha256 TEXT,
            expected_sha256 TEXT,
            size_bytes INTEGER,
            state TEXT NOT NULL CHECK(state IN (
                'present_match','present_new','duplicate_payload','missing_on_disk',
                'hash_mismatch','unreadable','corrupt_image'
            )),
            detail TEXT,
            observed_at TEXT NOT NULL,
            UNIQUE(corpus_run_id, manifestation_id)
        );
        CREATE INDEX IF NOT EXISTS ix_manifest_obs_run_state
            ON source_manifestation_observations(corpus_run_id, state);

        CREATE TABLE IF NOT EXISTS source_archives (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            locator TEXT NOT NULL UNIQUE,
            first_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS archive_observations (
            archive_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_run_id INTEGER NOT NULL REFERENCES corpus_freeze_runs(corpus_run_id),
            archive_id INTEGER NOT NULL REFERENCES source_archives(archive_id),
            outer_sha256 TEXT,
            size_bytes INTEGER,
            state TEXT NOT NULL CHECK(state IN ('scanned','unreadable')),
            error TEXT,
            observed_at TEXT NOT NULL,
            UNIQUE(corpus_run_id, archive_id)
        );

        CREATE TABLE IF NOT EXISTS archive_members (
            member_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_obs_id INTEGER NOT NULL REFERENCES archive_observations(archive_obs_id),
            member_path TEXT NOT NULL,
            uncompressed_size INTEGER,
            compressed_size INTEGER,
            member_sha256 TEXT,
            is_screenshot INTEGER NOT NULL CHECK(is_screenshot IN (0,1)),
            state TEXT NOT NULL CHECK(state IN ('scanned','unreadable')),
            error TEXT,
            UNIQUE(archive_obs_id, member_path)
        );
        CREATE INDEX IF NOT EXISTS ix_archive_members_sha
            ON archive_members(member_sha256);

        CREATE TABLE IF NOT EXISTS archive_equivalence (
            equivalence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_run_id INTEGER NOT NULL REFERENCES corpus_freeze_runs(corpus_run_id),
            left_archive_id INTEGER NOT NULL REFERENCES source_archives(archive_id),
            right_archive_id INTEGER NOT NULL REFERENCES source_archives(archive_id),
            classification TEXT NOT NULL CHECK(classification IN (
                'BYTE_IDENTICAL','PURE_RECOMPRESSION','SAME_PAYLOADS_DIFFERENT_PATHS',
                'DISTINCT_PAYLOADS','UNRESOLVED'
            )),
            detail_json TEXT NOT NULL,
            UNIQUE(corpus_run_id, left_archive_id, right_archive_id),
            CHECK(left_archive_id < right_archive_id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_certifications (
            gate_name TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('PASS','FAIL','OPEN','BLOCKED','PROVISIONAL')),
            bound_corpus_digest TEXT,
            evidence_sha256 TEXT,
            decided_at TEXT NOT NULL,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS screenshot_time_observations (
            time_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
            source_kind TEXT NOT NULL CHECK(source_kind IN (
                'filename','exif','device_visible','app_visible','filesystem'
            )),
            raw_value TEXT NOT NULL,
            normalized_value TEXT,
            authority TEXT NOT NULL CHECK(authority IN (
                'CANDIDATE_NOT_IDENTITY','CORROBORATING','AUTHORITATIVE','CONFLICTING'
            )),
            first_seen_at TEXT NOT NULL,
            UNIQUE(screenshot_id, source_kind, raw_value)
        );

        CREATE TABLE IF NOT EXISTS aircraft_identity_transition_audit (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            aircraft_obs_id INTEGER NOT NULL REFERENCES aircraft_observations(aircraft_obs_id),
            old_status TEXT,
            new_status TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS tr_ocr_requires_calibrated_corpus
        BEFORE INSERT ON ocr_observations
        WHEN NOT EXISTS (
            SELECT 1
            FROM pipeline_certifications c
            WHERE c.gate_name = 'RLSM_OCR_CALIBRATION'
              AND c.status = 'PASS'
              AND c.bound_corpus_digest = (
                  SELECT corpus_digest FROM corpus_freeze_runs
                  WHERE status='PASS' AND corpus_digest IS NOT NULL
                  ORDER BY corpus_run_id DESC LIMIT 1
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'RLSM_OCR_CALIBRATION is not PASS for the latest frozen corpus');
        END;

        CREATE TRIGGER IF NOT EXISTS tr_aircraft_ocr_only_not_confirmed
        AFTER INSERT ON aircraft_observations
        WHEN NEW.identity_status = 'confirmed'
          AND EXISTS (
              SELECT 1 FROM processing_runs r
              WHERE r.run_id = NEW.run_id AND r.run_kind = 'aircraft'
          )
        BEGIN
            INSERT INTO aircraft_identity_transition_audit
                (aircraft_obs_id, old_status, new_status, reason_code, observed_at)
            VALUES
                (NEW.aircraft_obs_id, 'confirmed', 'partial', 'OCR_ONLY_NOT_IDENTITY',
                 strftime('%Y-%m-%dT%H:%M:%SZ','now'));
            UPDATE aircraft_observations
               SET identity_status='partial',
                   confidence=CASE
                       WHEN confidence IS NULL THEN NULL
                       WHEN confidence > 0.75 THEN 0.75
                       ELSE confidence
                   END
             WHERE aircraft_obs_id=NEW.aircraft_obs_id;
        END;
        """
    )
    conn.commit()


def _upsert_manifestation(
    conn: sqlite3.Connection,
    *,
    source_kind: str,
    rel_path: str,
    screenshot_id: int | None,
    now: str,
) -> int:
    conn.execute(
        """INSERT INTO source_manifestations
           (source_kind, rel_path, screenshot_id, first_seen_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(source_kind, rel_path) DO UPDATE SET
             screenshot_id=COALESCE(source_manifestations.screenshot_id, excluded.screenshot_id)""",
        (source_kind, rel_path, screenshot_id, now),
    )
    row = conn.execute(
        "SELECT manifestation_id FROM source_manifestations WHERE source_kind=? AND rel_path=?",
        (source_kind, rel_path),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _record_manifestation_observation(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    manifestation_id: int,
    observed_sha256: str | None,
    expected_sha256: str | None,
    size_bytes: int | None,
    state: str,
    detail: str | None,
    now: str,
) -> None:
    conn.execute(
        """INSERT INTO source_manifestation_observations
           (corpus_run_id, manifestation_id, observed_sha256, expected_sha256,
            size_bytes, state, detail, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            corpus_run_id,
            manifestation_id,
            observed_sha256,
            expected_sha256,
            size_bytes,
            state,
            detail,
            now,
        ),
    )


def _decode_metadata(path: Path) -> tuple[int | None, int | None, str | None, str, str | None]:
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            phash = _ahash_8x8(img)
        return width, height, phash, "ok", None
    except Exception as exc:  # image bytes remain hashable evidence even if decode fails
        return None, None, None, "corrupt", f"{type(exc).__name__}: {exc}"[:400]


def _insert_logical_screenshot(
    conn: sqlite3.Connection,
    *,
    path: Path,
    rel_path: str,
    sha256: str,
    size_bytes: int,
    now: str,
) -> tuple[int, str]:
    existing = conn.execute(
        "SELECT screenshot_id FROM screenshots WHERE sha256=?", (sha256,)
    ).fetchone()
    if existing:
        return int(existing[0]), "duplicate_payload"

    width, height, phash, ingest_status, ingest_error = _decode_metadata(path)
    conn.execute(
        """INSERT INTO screenshots
           (sha256, filename, rel_path, month_bucket, filename_ts, ext, size_bytes,
            width, height, phash, ingest_status, ingest_error, ocr_status,
            source_availability, availability_checked_at, availability_detail,
            availability_source, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending',
                   'present', ?, 'ingested_from_source', 'corpus_freeze', ?)""",
        (
            sha256,
            path.name,
            rel_path,
            _month_bucket(path),
            _filename_ts(path.name),
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
    sid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return sid, "present_new" if ingest_status == "ok" else "corrupt_image"


def _scan_baseline(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    repo_root: Path,
    baseline: Path,
    deadline: float | None,
) -> dict:
    now = utc_now()
    db_rows = conn.execute(
        "SELECT screenshot_id, sha256, rel_path, filename_ts FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    by_rel = {str(row[2]): (int(row[0]), str(row[1])) for row in db_rows}

    # Every historical DB locator is a manifestation even if its bytes later moved.
    for sid, expected_sha, rel_path, filename_ts in db_rows:
        mid = _upsert_manifestation(
            conn,
            source_kind="historical_db_path",
            rel_path=str(rel_path),
            screenshot_id=int(sid),
            now=now,
        )
        if filename_ts:
            conn.execute(
                """INSERT OR IGNORE INTO screenshot_time_observations
                   (screenshot_id, source_kind, raw_value, normalized_value, authority, first_seen_at)
                   VALUES (?, 'filename', ?, ?, 'CANDIDATE_NOT_IDENTITY', ?)""",
                (sid, str(filename_ts), str(filename_ts), now),
            )
        candidate = repo_root / str(rel_path)
        if not candidate.is_file():
            _record_manifestation_observation(
                conn,
                corpus_run_id=corpus_run_id,
                manifestation_id=mid,
                observed_sha256=None,
                expected_sha256=str(expected_sha),
                size_bytes=None,
                state="missing_on_disk",
                detail="historical database pathname is not currently a file",
                now=now,
            )

    all_files = []
    if baseline.exists():
        all_files = sorted(
            p for p in baseline.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )

    counts = Counter()
    observed_baseline_paths: set[str] = set()
    partial = False
    for path in all_files:
        if deadline is not None and time.monotonic() >= deadline:
            partial = True
            break
        rel_path = _locator(path, repo_root)
        if rel_path.startswith("external:"):
            # Operational baseline paths are required to stay repository-relative.
            counts["unreadable"] += 1
            continue
        observed_baseline_paths.add(rel_path)
        historical = by_rel.get(rel_path)
        expected_sha = historical[1] if historical else None
        try:
            size = path.stat().st_size
            observed_sha = sha256_file(path)
        except OSError as exc:
            mid = _upsert_manifestation(
                conn,
                source_kind="baseline_file",
                rel_path=rel_path,
                screenshot_id=historical[0] if historical else None,
                now=now,
            )
            _record_manifestation_observation(
                conn,
                corpus_run_id=corpus_run_id,
                manifestation_id=mid,
                observed_sha256=None,
                expected_sha256=expected_sha,
                size_bytes=None,
                state="unreadable",
                detail=f"{type(exc).__name__}: {exc}"[:400],
                now=now,
            )
            counts["unreadable"] += 1
            continue

        if historical and observed_sha != expected_sha:
            sid = historical[0]
            state = "hash_mismatch"
            detail = "pathname bytes differ from the SHA-256 bound in screenshots"
        else:
            sid, state = _insert_logical_screenshot(
                conn,
                path=path,
                rel_path=rel_path,
                sha256=observed_sha,
                size_bytes=size,
                now=now,
            )
            detail = None

        mid = _upsert_manifestation(
            conn,
            source_kind="baseline_file",
            rel_path=rel_path,
            screenshot_id=sid,
            now=now,
        )
        _record_manifestation_observation(
            conn,
            corpus_run_id=corpus_run_id,
            manifestation_id=mid,
            observed_sha256=observed_sha,
            expected_sha256=expected_sha,
            size_bytes=size,
            state=state,
            detail=detail,
            now=now,
        )
        counts[state] += 1

    counts["discovered_files"] = len(all_files)
    counts["scanned_files"] = len(observed_baseline_paths)
    counts["partial"] = int(partial)
    return dict(counts)


def _archive_row(conn: sqlite3.Connection, locator: str, now: str) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO source_archives(locator, first_seen_at) VALUES (?, ?)",
        (locator, now),
    )
    row = conn.execute("SELECT archive_id FROM source_archives WHERE locator=?", (locator,)).fetchone()
    assert row is not None
    return int(row[0])


def _insert_archive_observation(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    archive_id: int,
    outer_sha256: str | None,
    size_bytes: int | None,
    state: str,
    error: str | None,
    now: str,
) -> int:
    conn.execute(
        """INSERT INTO archive_observations
           (corpus_run_id, archive_id, outer_sha256, size_bytes, state, error, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (corpus_run_id, archive_id, outer_sha256, size_bytes, state, error, now),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _hash_zip_members(path: Path) -> list[tuple[str, int, int | None, str | None, int, str, str | None]]:
    rows = []
    with zipfile.ZipFile(path, "r") as zf:
        for info in sorted(zf.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            member_path = info.filename
            try:
                with zf.open(info, "r") as handle:
                    digest = sha256_stream(handle)
                state, error = "scanned", None
            except Exception as exc:
                digest = None
                state, error = "unreadable", f"{type(exc).__name__}: {exc}"[:400]
            rows.append(
                (
                    member_path,
                    int(info.file_size),
                    int(info.compress_size),
                    digest,
                    int(Path(member_path).suffix.lower() in IMAGE_EXTS),
                    state,
                    error,
                )
            )
    return rows


def _hash_tar_members(path: Path) -> list[tuple[str, int, int | None, str | None, int, str, str | None]]:
    rows = []
    with tarfile.open(path, "r:*") as tf:
        members = sorted((m for m in tf.getmembers() if m.isfile()), key=lambda m: m.name)
        for member in members:
            try:
                handle = tf.extractfile(member)
                if handle is None:
                    raise OSError("member has no readable payload")
                with handle:
                    digest = sha256_stream(handle)
                state, error = "scanned", None
            except Exception as exc:
                digest = None
                state, error = "unreadable", f"{type(exc).__name__}: {exc}"[:400]
            rows.append(
                (
                    member.name,
                    int(member.size),
                    None,
                    digest,
                    int(Path(member.name).suffix.lower() in IMAGE_EXTS),
                    state,
                    error,
                )
            )
    return rows


def _scan_archives(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    repo_root: Path,
    archive_roots: Iterable[Path],
    deadline: float | None,
) -> dict:
    candidates: dict[str, Path] = {}
    for root in archive_roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and _is_archive(path):
                    candidates[_locator(path, repo_root)] = path

    now = utc_now()
    counts = Counter(discovered_archives=len(candidates))
    partial = False
    for locator, path in sorted(candidates.items()):
        if deadline is not None and time.monotonic() >= deadline:
            partial = True
            break
        archive_id = _archive_row(conn, locator, now)
        outer_sha = None
        size = None
        try:
            size = path.stat().st_size
            outer_sha = sha256_file(path)
            if path.name.lower().endswith(".zip"):
                members = _hash_zip_members(path)
            else:
                members = _hash_tar_members(path)
            archive_state, archive_error = "scanned", None
        except Exception as exc:
            members = []
            archive_state = "unreadable"
            archive_error = f"{type(exc).__name__}: {exc}"[:400]

        archive_obs_id = _insert_archive_observation(
            conn,
            corpus_run_id=corpus_run_id,
            archive_id=archive_id,
            outer_sha256=outer_sha,
            size_bytes=size,
            state=archive_state,
            error=archive_error,
            now=now,
        )
        counts[archive_state] += 1
        for member_path, raw_size, compressed_size, digest, is_screenshot, state, error in members:
            conn.execute(
                """INSERT INTO archive_members
                   (archive_obs_id, member_path, uncompressed_size, compressed_size,
                    member_sha256, is_screenshot, state, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    archive_obs_id,
                    member_path,
                    raw_size,
                    compressed_size,
                    digest,
                    is_screenshot,
                    state,
                    error,
                ),
            )
            counts["members"] += 1
            counts[f"member_{state}"] += 1
            if is_screenshot:
                counts["screenshot_members"] += 1

    counts["partial"] = int(partial)
    return dict(counts)


def _archive_signature(conn: sqlite3.Connection, archive_obs_id: int) -> tuple[Counter, Counter, bool]:
    path_payloads: Counter = Counter()
    payloads: Counter = Counter()
    unresolved = False
    for path, size, digest, state in conn.execute(
        """SELECT member_path, uncompressed_size, member_sha256, state
           FROM archive_members WHERE archive_obs_id=? ORDER BY member_path""",
        (archive_obs_id,),
    ):
        if state != "scanned" or not digest:
            unresolved = True
            continue
        path_payloads[(str(path), int(size or 0), str(digest))] += 1
        payloads[(int(size or 0), str(digest))] += 1
    return path_payloads, payloads, unresolved


def _classify_archives(conn: sqlite3.Connection, corpus_run_id: int) -> Counter:
    rows = conn.execute(
        """SELECT a.archive_id, o.archive_obs_id, o.outer_sha256, o.state
           FROM archive_observations o JOIN source_archives a USING(archive_id)
           WHERE o.corpus_run_id=? ORDER BY a.archive_id""",
        (corpus_run_id,),
    ).fetchall()
    counts: Counter = Counter()
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            left_id, left_obs, left_outer, left_state = left
            right_id, right_obs, right_outer, right_state = right
            if left_state != "scanned" or right_state != "scanned":
                classification = "UNRESOLVED"
            elif left_outer and left_outer == right_outer:
                classification = "BYTE_IDENTICAL"
            else:
                lpp, lp, lu = _archive_signature(conn, int(left_obs))
                rpp, rp, ru = _archive_signature(conn, int(right_obs))
                if lu or ru:
                    classification = "UNRESOLVED"
                elif lpp == rpp:
                    classification = "PURE_RECOMPRESSION"
                elif lp == rp:
                    classification = "SAME_PAYLOADS_DIFFERENT_PATHS"
                else:
                    classification = "DISTINCT_PAYLOADS"
            detail = {
                "left_outer_sha256": left_outer,
                "right_outer_sha256": right_outer,
            }
            conn.execute(
                """INSERT INTO archive_equivalence
                   (corpus_run_id, left_archive_id, right_archive_id, classification, detail_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (corpus_run_id, left_id, right_id, classification, stable_json(detail)),
            )
            counts[classification] += 1
    return counts


def _reconciliation_rows(conn: sqlite3.Connection, corpus_run_id: int) -> list[dict]:
    rows = []
    for values in conn.execute(
        """SELECT m.manifestation_id, m.source_kind, m.rel_path, m.screenshot_id,
                  o.observed_sha256, o.expected_sha256, o.size_bytes, o.state, o.detail
           FROM source_manifestations m
           JOIN source_manifestation_observations o USING(manifestation_id)
           WHERE o.corpus_run_id=?
           ORDER BY m.source_kind, m.rel_path""",
        (corpus_run_id,),
    ):
        keys = (
            "manifestation_id", "source_kind", "rel_path", "screenshot_id",
            "observed_sha256", "expected_sha256", "size_bytes", "state", "detail",
        )
        rows.append(dict(zip(keys, values, strict=True)))
    return rows


def _certify(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    baseline_counts: dict,
    archive_counts: dict,
    equivalence_counts: Counter,
) -> tuple[str, dict, str]:
    reconciliation = _reconciliation_rows(conn, corpus_run_id)
    state_counts = Counter(row["state"] for row in reconciliation)

    logical_rows = int(conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0])
    logical_unique = int(
        conn.execute("SELECT COUNT(DISTINCT sha256) FROM screenshots").fetchone()[0]
    )
    logical_sha_duplicate_rows = logical_rows - logical_unique

    baseline_obs = sum(1 for row in reconciliation if row["source_kind"] == "baseline_file")
    baseline_closed = baseline_obs == int(baseline_counts.get("scanned_files", 0))

    archive_obs = int(
        conn.execute(
            "SELECT COUNT(*) FROM archive_observations WHERE corpus_run_id=?",
            (corpus_run_id,),
        ).fetchone()[0]
    )
    archive_members = int(
        conn.execute(
            """SELECT COUNT(*) FROM archive_members m
               JOIN archive_observations o USING(archive_obs_id)
               WHERE o.corpus_run_id=?""",
            (corpus_run_id,),
        ).fetchone()[0]
    )
    archive_closed = (
        archive_obs == int(archive_counts.get("scanned", 0)) + int(archive_counts.get("unreadable", 0))
        and archive_members == int(archive_counts.get("members", 0))
    )

    archive_only = int(
        conn.execute(
            """SELECT COUNT(DISTINCT m.member_sha256)
               FROM archive_members m JOIN archive_observations o USING(archive_obs_id)
               WHERE o.corpus_run_id=? AND m.is_screenshot=1 AND m.state='scanned'
                 AND m.member_sha256 IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM screenshots s WHERE s.sha256=m.member_sha256)""",
            (corpus_run_id,),
        ).fetchone()[0]
    )

    unexplained = (
        int(state_counts.get("hash_mismatch", 0))
        + int(state_counts.get("unreadable", 0))
        + int(archive_counts.get("unreadable", 0))
        + int(archive_counts.get("member_unreadable", 0))
        + logical_sha_duplicate_rows
        + (0 if baseline_closed else 1)
        + (0 if archive_closed else 1)
    )
    partial = bool(baseline_counts.get("partial") or archive_counts.get("partial"))

    if partial:
        status = "OPEN_PARTIAL"
    elif unexplained:
        status = "FAIL"
    else:
        status = "PASS"

    counts = {
        "logical_screenshots": logical_rows,
        "logical_unique_sha256": logical_unique,
        "logical_sha_duplicate_rows": logical_sha_duplicate_rows,
        "baseline": baseline_counts,
        "manifestation_states": dict(sorted(state_counts.items())),
        "archives": archive_counts,
        "archive_equivalence": dict(sorted(equivalence_counts.items())),
        "archive_only_screenshot_payloads": archive_only,
        "baseline_arithmetic_closed": baseline_closed,
        "archive_arithmetic_closed": archive_closed,
        "unexplained_residue": unexplained,
    }
    digest_material = {
        "protocol": CORPUS_PROTOCOL,
        "logical": [
            list(row)
            for row in conn.execute(
                "SELECT screenshot_id, sha256, rel_path, size_bytes FROM screenshots ORDER BY screenshot_id"
            )
        ],
        "manifestations": reconciliation,
        "archives": [
            list(row)
            for row in conn.execute(
                """SELECT a.locator, o.outer_sha256, o.size_bytes, o.state, o.error
                   FROM archive_observations o JOIN source_archives a USING(archive_id)
                   WHERE o.corpus_run_id=? ORDER BY a.locator""",
                (corpus_run_id,),
            )
        ],
        "members": [
            list(row)
            for row in conn.execute(
                """SELECT a.locator, m.member_path, m.uncompressed_size, m.member_sha256,
                          m.is_screenshot, m.state
                   FROM archive_members m
                   JOIN archive_observations o USING(archive_obs_id)
                   JOIN source_archives a USING(archive_id)
                   WHERE o.corpus_run_id=? ORDER BY a.locator, m.member_path""",
                (corpus_run_id,),
            )
        ],
    }
    corpus_digest = hashlib.sha256(stable_json(digest_material).encode("utf-8")).hexdigest()

    calibration = conn.execute(
        "SELECT status, bound_corpus_digest FROM pipeline_certifications WHERE gate_name=?",
        (OCR_GATE,),
    ).fetchone()
    calibration_pass = bool(calibration and calibration[0] == "PASS" and calibration[1] == corpus_digest)
    mass_ocr_ready = status == "PASS" and archive_only == 0 and calibration_pass

    certification = {
        "protocol": CORPUS_PROTOCOL,
        "scope": "RLSM_SCREENSHOT_CORPUS_INGEST",
        "status": status,
        "corpus_digest": corpus_digest,
        "counts": counts,
        "gates": {
            "corpus_freeze_pass": status == "PASS",
            "zero_unexplained_ingest_residue": unexplained == 0,
            "logical_sha_uniqueness": logical_sha_duplicate_rows == 0,
            "baseline_arithmetic_closed": baseline_closed,
            "archive_arithmetic_closed": archive_closed,
            "archive_only_screenshot_payloads_zero": archive_only == 0,
            "ocr_calibration_bound_pass": calibration_pass,
            "mass_ocr_ready": mass_ocr_ready,
        },
        "nonclaims": [
            "filename timestamps are candidate evidence only",
            "OCR text is not aircraft identity",
            "map labels are not aircraft position",
            "co-occurrence/proximity/route similarity are not coordination",
        ],
    }
    return status, certification, corpus_digest


def _invalidate_stale_calibration(conn: sqlite3.Connection, corpus_digest: str) -> None:
    row = conn.execute(
        "SELECT status, bound_corpus_digest FROM pipeline_certifications WHERE gate_name=?",
        (OCR_GATE,),
    ).fetchone()
    if row and row[0] == "PASS" and row[1] != corpus_digest:
        conn.execute(
            """UPDATE pipeline_certifications
               SET status='OPEN', bound_corpus_digest=?, evidence_sha256=NULL,
                   decided_at=?, detail='corpus digest changed; empirical calibration must be re-bound'
               WHERE gate_name=?""",
            (corpus_digest, utc_now(), OCR_GATE),
        )
    elif row is None:
        conn.execute(
            """INSERT INTO pipeline_certifications
               (gate_name, status, bound_corpus_digest, evidence_sha256, decided_at, detail)
               VALUES (?, 'OPEN', ?, NULL, ?, 'empirical OCR calibration has not yet been executed')""",
            (OCR_GATE, corpus_digest, utc_now()),
        )


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_artifacts(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    certification: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_rows = []
    for row in conn.execute(
        """SELECT screenshot_id, sha256, filename, rel_path, month_bucket, filename_ts,
                  ext, size_bytes, width, height, phash, ingest_status, ingest_error,
                  ocr_status, source_availability
           FROM screenshots ORDER BY screenshot_id"""
    ):
        keys = (
            "screenshot_id", "sha256", "filename", "rel_path", "month_bucket",
            "filename_ts", "ext", "size_bytes", "width", "height", "phash",
            "ingest_status", "ingest_error", "ocr_status", "source_availability",
        )
        corpus_rows.append(dict(zip(keys, row, strict=True)))
    _write_csv(output_dir / "01_corpus_manifest.csv", corpus_rows, list(corpus_rows[0]) if corpus_rows else ["screenshot_id"])

    member_rows = []
    for row in conn.execute(
        """SELECT a.locator, o.outer_sha256, m.member_path, m.uncompressed_size,
                  m.compressed_size, m.member_sha256, m.is_screenshot, m.state, m.error
           FROM archive_members m
           JOIN archive_observations o USING(archive_obs_id)
           JOIN source_archives a USING(archive_id)
           WHERE o.corpus_run_id=? ORDER BY a.locator, m.member_path""",
        (corpus_run_id,),
    ):
        keys = (
            "archive_locator", "outer_sha256", "member_path", "uncompressed_size",
            "compressed_size", "member_sha256", "is_screenshot", "state", "error",
        )
        member_rows.append(dict(zip(keys, row, strict=True)))
    _write_csv(
        output_dir / "02_archive_member_manifest.csv",
        member_rows,
        list(member_rows[0]) if member_rows else ["archive_locator"],
    )

    rec_rows = _reconciliation_rows(conn, corpus_run_id)
    _write_csv(
        output_dir / "03_db_filesystem_reconciliation.csv",
        rec_rows,
        list(rec_rows[0]) if rec_rows else ["manifestation_id"],
    )

    dup_rows = []
    for sha, count in conn.execute(
        """SELECT o.observed_sha256, COUNT(*)
           FROM source_manifestation_observations o
           JOIN source_manifestations m USING(manifestation_id)
           WHERE o.corpus_run_id=? AND o.observed_sha256 IS NOT NULL
           GROUP BY o.observed_sha256 HAVING COUNT(*) > 1
           ORDER BY o.observed_sha256""",
        (corpus_run_id,),
    ):
        paths = [
            r[0]
            for r in conn.execute(
                """SELECT m.rel_path FROM source_manifestation_observations o
                   JOIN source_manifestations m USING(manifestation_id)
                   WHERE o.corpus_run_id=? AND o.observed_sha256=?
                   ORDER BY m.rel_path""",
                (corpus_run_id, sha),
            )
        ]
        dup_rows.append(
            {
                "sha256": sha,
                "manifestation_count": count,
                "manifestation_paths_json": stable_json(paths),
            }
        )
    _write_csv(
        output_dir / "04_duplicate_groups.csv",
        dup_rows,
        ["sha256", "manifestation_count", "manifestation_paths_json"],
    )

    equivalence_rows = []
    for row in conn.execute(
        """SELECT la.locator, ra.locator, e.classification, e.detail_json
           FROM archive_equivalence e
           JOIN source_archives la ON la.archive_id=e.left_archive_id
           JOIN source_archives ra ON ra.archive_id=e.right_archive_id
           WHERE e.corpus_run_id=? ORDER BY la.locator, ra.locator""",
        (corpus_run_id,),
    ):
        equivalence_rows.append(
            {
                "left_archive": row[0],
                "right_archive": row[1],
                "classification": row[2],
                "detail_json": row[3],
            }
        )
    _write_csv(
        output_dir / "04_archive_equivalence.csv",
        equivalence_rows,
        ["left_archive", "right_archive", "classification", "detail_json"],
    )

    (output_dir / "05_ingest_certification.json").write_text(
        json.dumps(certification, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(
    *,
    db_path: Path = DB_PATH,
    repo_root: Path = REPO,
    baseline: Path = BASELINE,
    archive_roots: Iterable[Path] = DEFAULT_ARCHIVE_ROOTS,
    output_dir: Path = OUTPUT_DIR,
    budget_sec: float = 0,
) -> dict:
    if not baseline.exists():
        raise RuntimeError(f"baseline directory not found: {baseline}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    ensure_base_schema(conn)
    ensure_corpus_schema(conn)

    started = utc_now()
    roots = [Path(root) for root in archive_roots]
    cur = conn.execute(
        """INSERT INTO corpus_freeze_runs
           (protocol, started_at, status, baseline_root, archive_roots_json)
           VALUES (?, ?, 'IN_PROGRESS', ?, ?)""",
        (
            CORPUS_PROTOCOL,
            started,
            _locator(baseline, repo_root),
            stable_json([_locator(root, repo_root) for root in roots]),
        ),
    )
    corpus_run_id = int(cur.lastrowid)
    conn.commit()

    deadline = time.monotonic() + budget_sec if budget_sec and budget_sec > 0 else None
    try:
        conn.execute("BEGIN IMMEDIATE")
        baseline_counts = _scan_baseline(
            conn,
            corpus_run_id=corpus_run_id,
            repo_root=repo_root,
            baseline=baseline,
            deadline=deadline,
        )
        archive_counts = _scan_archives(
            conn,
            corpus_run_id=corpus_run_id,
            repo_root=repo_root,
            archive_roots=roots,
            deadline=deadline,
        )
        equivalence_counts = _classify_archives(conn, corpus_run_id)
        status, certification, corpus_digest = _certify(
            conn,
            corpus_run_id=corpus_run_id,
            baseline_counts=baseline_counts,
            archive_counts=archive_counts,
            equivalence_counts=equivalence_counts,
        )
        _invalidate_stale_calibration(conn, corpus_digest)
        # Re-evaluate readiness after stale calibration invalidation.
        calibration = conn.execute(
            "SELECT status, bound_corpus_digest FROM pipeline_certifications WHERE gate_name=?",
            (OCR_GATE,),
        ).fetchone()
        certification["gates"]["ocr_calibration_bound_pass"] = bool(
            calibration and calibration[0] == "PASS" and calibration[1] == corpus_digest
        )
        certification["gates"]["mass_ocr_ready"] = bool(
            status == "PASS"
            and certification["counts"]["archive_only_screenshot_payloads"] == 0
            and certification["gates"]["ocr_calibration_bound_pass"]
        )
        conn.execute(
            """UPDATE corpus_freeze_runs
               SET ended_at=?, status=?, corpus_digest=?, counts_json=?, certification_json=?
               WHERE corpus_run_id=?""",
            (
                utc_now(),
                status,
                corpus_digest,
                stable_json(certification["counts"]),
                stable_json(certification),
                corpus_run_id,
            ),
        )
        conn.commit()
        write_artifacts(
            conn,
            corpus_run_id=corpus_run_id,
            certification=certification,
            output_dir=output_dir,
        )
        return certification
    except Exception:
        conn.rollback()
        conn.execute(
            "UPDATE corpus_freeze_runs SET ended_at=?, status='FAIL' WHERE corpus_run_id=?",
            (utc_now(), corpus_run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and reconcile the RLSM screenshot corpus.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--archive-root", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--budget-sec",
        type=float,
        default=0,
        help="Optional wall-clock cap. Any cap that truncates traversal yields OPEN_PARTIAL, never PASS.",
    )
    args = parser.parse_args()
    roots = args.archive_root or list(DEFAULT_ARCHIVE_ROOTS)
    result = run(
        db_path=args.db,
        repo_root=args.repo_root,
        baseline=args.baseline,
        archive_roots=roots,
        output_dir=args.output_dir,
        budget_sec=args.budget_sec,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
