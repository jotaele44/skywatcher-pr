"""Provenance-first RLSM screenshot corpus freeze.

``screenshots`` remains the stable downstream logical-payload table: one row per
unique SHA-256. Every filesystem pathname and every archive member is preserved
separately as a source manifestation. This prevents exact duplicates from being
erased while keeping all existing screenshot foreign keys stable.

The freeze is fail-closed. A truncated traversal, directory traversal error,
unfollowed nested directory symlink, unreadable bytes, pathname/hash
contradiction, archive/member read failure, or arithmetic mismatch cannot
produce ``PASS``. This stage performs no OCR and cannot promote filename, OCR,
map-label, proximity, co-occurrence, or route-similarity evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tarfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

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
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)
CORPUS_PROTOCOL = "rlsm-corpus-freeze-v1.0"
OCR_GATE = "RLSM_OCR_CALIBRATION"
_FILENAME_TS_RE = re.compile(
    r"(?P<y>20\d{2})[-_]?(?P<mo>\d{2})[-_]?(?P<d>\d{2})"
    r"[ _T]?(?P<h>\d{2})[-_.:]?(?P<mi>\d{2})(?:[-_.:]?(?P<s>\d{2}))?"
)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_stream(handle: BinaryIO, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(chunk_size), b""):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle)


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_archive(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _locator(path: Path, repo_root: Path) -> str:
    """Return a stable locator without resolving an operational corpus symlink."""
    absolute = path.absolute()
    root_absolute = repo_root.absolute()
    try:
        return absolute.relative_to(root_absolute).as_posix()
    except ValueError:
        return "external:" + str(path.resolve())


def _filename_ts(name: str) -> str | None:
    match = _FILENAME_TS_RE.search(Path(name).name)
    if not match:
        return None
    values = match.groupdict()
    second = values.get("s") or "00"
    return (
        f"{values['y']}-{values['mo']}-{values['d']}T"
        f"{values['h']}:{values['mi']}:{second}"
    )


def _month_bucket(path: Path) -> str | None:
    parent = path.parent.name
    if (
        len(parent) == 7
        and parent[4] == "-"
        and parent[:4].isdigit()
        and parent[5:].isdigit()
    ):
        return parent
    return None


def _ahash_8x8(img: Image.Image) -> str:
    gray = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    average = sum(pixels) / 64
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _discover_files(
    root: Path, predicate: Callable[[Path], bool]
) -> tuple[list[Path], list[str], list[str]]:
    """Deterministically walk ``root`` and expose traversal/symlink omissions."""
    files: list[Path] = []
    errors: list[str] = []
    symlink_dirs: list[str] = []
    if not root.exists():
        return files, errors, symlink_dirs

    def onerror(exc: OSError) -> None:
        errors.append(f"{type(exc).__name__}: {exc}")

    for current, directories, filenames in os.walk(
        root, topdown=True, onerror=onerror, followlinks=False
    ):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        kept_directories = []
        for directory in directories:
            candidate = current_path / directory
            if candidate.is_symlink():
                symlink_dirs.append(str(candidate))
            else:
                kept_directories.append(directory)
        directories[:] = kept_directories
        for filename in filenames:
            candidate = current_path / filename
            if predicate(candidate):
                files.append(candidate)
    return files, errors, symlink_dirs


def ensure_base_schema(conn: sqlite3.Connection, schema_sql: Path = SCHEMA_SQL) -> None:
    if schema_sql.exists():
        conn.executescript(schema_sql.read_text(encoding="utf-8"))
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screenshots'"
    ).fetchone()
    if not exists:
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
            status TEXT NOT NULL
                CHECK(status IN ('IN_PROGRESS','PASS','FAIL','OPEN_PARTIAL')),
            baseline_root TEXT NOT NULL,
            archive_roots_json TEXT NOT NULL,
            corpus_digest TEXT,
            counts_json TEXT,
            certification_json TEXT
        );

        CREATE TABLE IF NOT EXISTS source_manifestations (
            manifestation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL
                CHECK(source_kind IN ('baseline_file','historical_db_path')),
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
            member_ordinal INTEGER NOT NULL,
            member_path TEXT NOT NULL,
            uncompressed_size INTEGER,
            compressed_size INTEGER,
            member_sha256 TEXT,
            is_screenshot INTEGER NOT NULL CHECK(is_screenshot IN (0,1)),
            state TEXT NOT NULL CHECK(state IN ('scanned','unreadable')),
            error TEXT,
            UNIQUE(archive_obs_id, member_ordinal)
        );
        CREATE INDEX IF NOT EXISTS ix_archive_members_sha ON archive_members(member_sha256);

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
            status TEXT NOT NULL
                CHECK(status IN ('PASS','FAIL','OPEN','BLOCKED','PROVISIONAL')),
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

        DROP TRIGGER IF EXISTS tr_ocr_requires_calibrated_corpus;
        CREATE TRIGGER tr_ocr_requires_calibrated_corpus
        BEFORE INSERT ON ocr_observations
        WHEN NOT EXISTS (
            SELECT 1 FROM pipeline_certifications c
            WHERE c.gate_name = 'RLSM_OCR_CALIBRATION'
              AND c.status = 'PASS'
              AND c.bound_corpus_digest = (
                  SELECT corpus_digest FROM corpus_freeze_runs
                  WHERE status='PASS' AND corpus_digest IS NOT NULL
                  ORDER BY corpus_run_id DESC LIMIT 1
              )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'RLSM_OCR_CALIBRATION is not PASS for the latest frozen corpus'
            );
        END;

        DROP TRIGGER IF EXISTS tr_aircraft_ocr_only_not_confirmed;
        CREATE TRIGGER tr_aircraft_ocr_only_not_confirmed
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
        """SELECT manifestation_id FROM source_manifestations
           WHERE source_kind=? AND rel_path=?""",
        (source_kind, rel_path),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _ensure_historical_manifestations(conn: sqlite3.Connection, now: str) -> None:
    for screenshot_id, rel_path in conn.execute(
        "SELECT screenshot_id, rel_path FROM screenshots ORDER BY screenshot_id"
    ):
        _upsert_manifestation(
            conn,
            source_kind="historical_db_path",
            rel_path=str(rel_path),
            screenshot_id=int(screenshot_id),
            now=now,
        )


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


def _decode_metadata(
    path: Path,
) -> tuple[int | None, int | None, str | None, str, str | None]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            phash = _ahash_8x8(image)
        return width, height, phash, "ok", None
    except Exception as exc:  # noqa: BLE001 - decoding errors are evidence states
        detail = f"{type(exc).__name__}: {exc}"[:400]
        return None, None, None, "corrupt", detail


def _insert_or_bind_logical_screenshot(
    conn: sqlite3.Connection,
    *,
    path: Path,
    rel_path: str,
    sha256: str,
    size_bytes: int,
    now: str,
) -> tuple[int, str]:
    existing = conn.execute(
        "SELECT screenshot_id, rel_path FROM screenshots WHERE sha256=?", (sha256,)
    ).fetchone()
    if existing:
        state = "present_match" if str(existing[1]) == rel_path else "duplicate_payload"
        return int(existing[0]), state

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
    screenshot_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    state = "present_new" if ingest_status == "ok" else "corrupt_image"
    return screenshot_id, state


def _scan_baseline(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    repo_root: Path,
    baseline: Path,
    deadline: float | None,
) -> dict:
    now = utc_now()
    database_rows = conn.execute(
        "SELECT screenshot_id, sha256, rel_path, filename_ts FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    by_rel = {str(row[2]): (int(row[0]), str(row[1])) for row in database_rows}

    for screenshot_id, _expected_sha, rel_path, filename_ts in database_rows:
        _upsert_manifestation(
            conn,
            source_kind="historical_db_path",
            rel_path=str(rel_path),
            screenshot_id=int(screenshot_id),
            now=now,
        )
        if filename_ts:
            conn.execute(
                """INSERT OR IGNORE INTO screenshot_time_observations
                   (screenshot_id, source_kind, raw_value, normalized_value,
                    authority, first_seen_at)
                   VALUES (?, 'filename', ?, ?, 'CANDIDATE_NOT_IDENTITY', ?)""",
                (screenshot_id, str(filename_ts), str(filename_ts), now),
            )

    all_files, traversal_errors, symlink_dirs = _discover_files(
        baseline, lambda path: path.suffix.lower() in IMAGE_EXTS
    )
    discovered_rel_paths = {_locator(path, repo_root) for path in all_files}

    for screenshot_id, expected_sha, rel_path, _filename_ts_value in database_rows:
        if str(rel_path) in discovered_rel_paths:
            continue
        manifestation_id = _upsert_manifestation(
            conn,
            source_kind="historical_db_path",
            rel_path=str(rel_path),
            screenshot_id=int(screenshot_id),
            now=now,
        )
        _record_manifestation_observation(
            conn,
            corpus_run_id=corpus_run_id,
            manifestation_id=manifestation_id,
            observed_sha256=None,
            expected_sha256=str(expected_sha),
            size_bytes=None,
            state="missing_on_disk",
            detail="historical database pathname is absent from the current baseline denominator",
            now=now,
        )

    counts: Counter[str] = Counter()
    scanned_count = 0
    partial = False
    for path in all_files:
        if deadline is not None and time.monotonic() >= deadline:
            partial = True
            break
        rel_path = _locator(path, repo_root)
        historical = by_rel.get(rel_path)
        expected_sha = historical[1] if historical else None
        scanned_count += 1
        try:
            size_bytes = path.stat().st_size
            observed_sha = sha256_file(path)
        except OSError as exc:
            manifestation_id = _upsert_manifestation(
                conn,
                source_kind="baseline_file",
                rel_path=rel_path,
                screenshot_id=historical[0] if historical else None,
                now=now,
            )
            _record_manifestation_observation(
                conn,
                corpus_run_id=corpus_run_id,
                manifestation_id=manifestation_id,
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
            screenshot_id = historical[0]
            state = "hash_mismatch"
            detail = "pathname bytes differ from the SHA-256 bound in screenshots"
            bound_sha = expected_sha
        else:
            screenshot_id, state = _insert_or_bind_logical_screenshot(
                conn,
                path=path,
                rel_path=rel_path,
                sha256=observed_sha,
                size_bytes=size_bytes,
                now=now,
            )
            detail = None
            bound_sha = observed_sha

        manifestation_id = _upsert_manifestation(
            conn,
            source_kind="baseline_file",
            rel_path=rel_path,
            screenshot_id=screenshot_id,
            now=now,
        )
        _record_manifestation_observation(
            conn,
            corpus_run_id=corpus_run_id,
            manifestation_id=manifestation_id,
            observed_sha256=observed_sha,
            expected_sha256=bound_sha,
            size_bytes=size_bytes,
            state=state,
            detail=detail,
            now=now,
        )
        counts[state] += 1

    _ensure_historical_manifestations(conn, now)
    counts["discovered_files"] = len(all_files)
    counts["scanned_files"] = scanned_count
    counts["traversal_errors"] = len(traversal_errors)
    counts["unfollowed_symlink_dirs"] = len(symlink_dirs)
    counts["partial"] = int(partial)
    return dict(counts)


def _archive_id(conn: sqlite3.Connection, locator: str, now: str) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO source_archives(locator, first_seen_at) VALUES (?, ?)",
        (locator, now),
    )
    row = conn.execute(
        "SELECT archive_id FROM source_archives WHERE locator=?", (locator,)
    ).fetchone()
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


def _zip_members(
    path: Path,
) -> list[tuple[int, str, int, int | None, str | None, int, str, str | None]]:
    rows = []
    with zipfile.ZipFile(path, "r") as archive:
        ordinal = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            ordinal += 1
            try:
                with archive.open(info, "r") as handle:
                    digest = sha256_stream(handle)
                state, error = "scanned", None
            except Exception as exc:  # noqa: BLE001 - member failure is evidence
                digest = None
                state = "unreadable"
                error = f"{type(exc).__name__}: {exc}"[:400]
            rows.append(
                (
                    ordinal,
                    info.filename,
                    int(info.file_size),
                    int(info.compress_size),
                    digest,
                    int(Path(info.filename).suffix.lower() in IMAGE_EXTS),
                    state,
                    error,
                )
            )
    return rows


def _tar_members(
    path: Path,
) -> list[tuple[int, str, int, int | None, str | None, int, str, str | None]]:
    rows = []
    with tarfile.open(path, "r:*") as archive:
        ordinal = 0
        for member in archive.getmembers():
            if not member.isfile():
                continue
            ordinal += 1
            try:
                handle = archive.extractfile(member)
                if handle is None:
                    raise OSError("member has no readable payload")
                with handle:
                    digest = sha256_stream(handle)
                state, error = "scanned", None
            except Exception as exc:  # noqa: BLE001 - member failure is evidence
                digest = None
                state = "unreadable"
                error = f"{type(exc).__name__}: {exc}"[:400]
            rows.append(
                (
                    ordinal,
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
    traversal_errors: list[str] = []
    symlink_dirs: list[str] = []
    for root in archive_roots:
        root_files, root_errors, root_symlink_dirs = _discover_files(root, _is_archive)
        traversal_errors.extend(root_errors)
        symlink_dirs.extend(root_symlink_dirs)
        for path in root_files:
            candidates[_locator(path, repo_root)] = path

    now = utc_now()
    counts: Counter[str] = Counter()
    counts["discovered_archives"] = len(candidates)
    partial = False
    for locator, path in sorted(candidates.items()):
        if deadline is not None and time.monotonic() >= deadline:
            partial = True
            break
        archive_id = _archive_id(conn, locator, now)
        outer_sha = None
        size_bytes = None
        try:
            size_bytes = path.stat().st_size
            outer_sha = sha256_file(path)
            members = _zip_members(path) if path.name.lower().endswith(".zip") else _tar_members(path)
            state, error = "scanned", None
        except Exception as exc:  # noqa: BLE001 - archive failure is classified evidence
            members = []
            state = "unreadable"
            error = f"{type(exc).__name__}: {exc}"[:400]

        archive_obs_id = _insert_archive_observation(
            conn,
            corpus_run_id=corpus_run_id,
            archive_id=archive_id,
            outer_sha256=outer_sha,
            size_bytes=size_bytes,
            state=state,
            error=error,
            now=now,
        )
        counts[state] += 1
        for (
            ordinal,
            member_path,
            raw_size,
            compressed_size,
            digest,
            is_screenshot,
            member_state,
            member_error,
        ) in members:
            conn.execute(
                """INSERT INTO archive_members
                   (archive_obs_id, member_ordinal, member_path, uncompressed_size,
                    compressed_size, member_sha256, is_screenshot, state, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    archive_obs_id,
                    ordinal,
                    member_path,
                    raw_size,
                    compressed_size,
                    digest,
                    is_screenshot,
                    member_state,
                    member_error,
                ),
            )
            counts["members"] += 1
            counts[f"member_{member_state}"] += 1
            if is_screenshot:
                counts["screenshot_members"] += 1

    counts["traversal_errors"] = len(traversal_errors)
    counts["unfollowed_symlink_dirs"] = len(symlink_dirs)
    counts["partial"] = int(partial)
    return dict(counts)


def _archive_signature(
    conn: sqlite3.Connection, archive_obs_id: int
) -> tuple[Counter[tuple[str, int, str]], Counter[tuple[int, str]], bool]:
    path_payloads: Counter[tuple[str, int, str]] = Counter()
    payloads: Counter[tuple[int, str]] = Counter()
    unresolved = False
    rows = conn.execute(
        """SELECT member_path, uncompressed_size, member_sha256, state
           FROM archive_members WHERE archive_obs_id=? ORDER BY member_ordinal""",
        (archive_obs_id,),
    )
    for path, size, digest, state in rows:
        if state != "scanned" or not digest:
            unresolved = True
            continue
        path_payloads[(str(path), int(size or 0), str(digest))] += 1
        payloads[(int(size or 0), str(digest))] += 1
    return path_payloads, payloads, unresolved


def _classify_archives(conn: sqlite3.Connection, corpus_run_id: int) -> Counter[str]:
    rows = conn.execute(
        """SELECT a.archive_id, o.archive_obs_id, o.outer_sha256, o.state
           FROM archive_observations o JOIN source_archives a USING(archive_id)
           WHERE o.corpus_run_id=? ORDER BY a.archive_id""",
        (corpus_run_id,),
    ).fetchall()
    counts: Counter[str] = Counter()
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            left_id, left_obs, left_outer, left_state = left
            right_id, right_obs, right_outer, right_state = right
            if left_outer and left_outer == right_outer:
                classification = "BYTE_IDENTICAL"
            elif left_state != "scanned" or right_state != "scanned":
                classification = "UNRESOLVED"
            else:
                left_path_payloads, left_payloads, left_unresolved = _archive_signature(
                    conn, int(left_obs)
                )
                right_path_payloads, right_payloads, right_unresolved = _archive_signature(
                    conn, int(right_obs)
                )
                if left_unresolved or right_unresolved:
                    classification = "UNRESOLVED"
                elif left_path_payloads == right_path_payloads:
                    classification = "PURE_RECOMPRESSION"
                elif left_payloads == right_payloads:
                    classification = "SAME_PAYLOADS_DIFFERENT_PATHS"
                else:
                    classification = "DISTINCT_PAYLOADS"
            detail = {
                "left_outer_sha256": left_outer,
                "right_outer_sha256": right_outer,
            }
            conn.execute(
                """INSERT INTO archive_equivalence
                   (corpus_run_id, left_archive_id, right_archive_id,
                    classification, detail_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (corpus_run_id, left_id, right_id, classification, stable_json(detail)),
            )
            counts[classification] += 1
    return counts


def _reconciliation_rows(conn: sqlite3.Connection, corpus_run_id: int) -> list[dict]:
    output = []
    rows = conn.execute(
        """SELECT m.manifestation_id, m.source_kind, m.rel_path, m.screenshot_id,
                  o.observed_sha256, o.expected_sha256, o.size_bytes, o.state, o.detail
           FROM source_manifestations m
           JOIN source_manifestation_observations o USING(manifestation_id)
           WHERE o.corpus_run_id=?
           ORDER BY m.source_kind, m.rel_path""",
        (corpus_run_id,),
    )
    keys = (
        "manifestation_id",
        "source_kind",
        "rel_path",
        "screenshot_id",
        "observed_sha256",
        "expected_sha256",
        "size_bytes",
        "state",
        "detail",
    )
    for values in rows:
        output.append(dict(zip(keys, values, strict=True)))
    return output


def _normalized_manifestation_state(state: str) -> str:
    if state in {"present_new", "present_match"}:
        return "PRESENT"
    return state.upper()


def _corpus_digest(
    conn: sqlite3.Connection, corpus_run_id: int, reconciliation: list[dict]
) -> str:
    """Hash canonical source identity, not processing-history accidents."""
    bound_sha = {
        int(screenshot_id): str(sha256)
        for screenshot_id, sha256 in conn.execute(
            "SELECT screenshot_id, sha256 FROM screenshots"
        )
    }
    stable_manifestation_identities = [
        [source_kind, rel_path, bound_sha.get(int(screenshot_id)) if screenshot_id else None]
        for source_kind, rel_path, screenshot_id in conn.execute(
            """SELECT source_kind, rel_path, screenshot_id
               FROM source_manifestations ORDER BY source_kind, rel_path"""
        )
    ]
    current_observations = [
        [
            row["source_kind"],
            row["rel_path"],
            bound_sha.get(int(row["screenshot_id"])) if row["screenshot_id"] else None,
            row["observed_sha256"],
            row["size_bytes"],
            _normalized_manifestation_state(str(row["state"])),
        ]
        for row in reconciliation
    ]
    material = {
        "protocol": CORPUS_PROTOCOL,
        "logical_payloads": [
            list(row)
            for row in conn.execute(
                "SELECT sha256, size_bytes FROM screenshots ORDER BY sha256, size_bytes"
            )
        ],
        "manifestation_identities": stable_manifestation_identities,
        "manifestation_observations": current_observations,
        "archives": [
            list(row)
            for row in conn.execute(
                """SELECT a.locator, o.outer_sha256, o.size_bytes, o.state
                   FROM archive_observations o JOIN source_archives a USING(archive_id)
                   WHERE o.corpus_run_id=? ORDER BY a.locator""",
                (corpus_run_id,),
            )
        ],
        "archive_members": [
            list(row)
            for row in conn.execute(
                """SELECT a.locator, m.member_ordinal, m.member_path,
                          m.uncompressed_size, m.member_sha256, m.is_screenshot, m.state
                   FROM archive_members m
                   JOIN archive_observations o USING(archive_obs_id)
                   JOIN source_archives a USING(archive_id)
                   WHERE o.corpus_run_id=? ORDER BY a.locator, m.member_ordinal""",
                (corpus_run_id,),
            )
        ],
    }
    return hashlib.sha256(stable_json(material).encode("utf-8")).hexdigest()


def _certify(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    baseline_counts: dict,
    archive_counts: dict,
    equivalence_counts: Counter[str],
) -> tuple[str, dict, str]:
    reconciliation = _reconciliation_rows(conn, corpus_run_id)
    state_counts = Counter(row["state"] for row in reconciliation)

    logical_rows = int(conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0])
    logical_unique = int(
        conn.execute("SELECT COUNT(DISTINCT sha256) FROM screenshots").fetchone()[0]
    )
    logical_sha_duplicate_rows = logical_rows - logical_unique

    baseline_observations = sum(
        row["source_kind"] == "baseline_file" for row in reconciliation
    )
    baseline_closed = baseline_observations == int(baseline_counts.get("scanned_files", 0))
    baseline_traversal_complete = (
        not baseline_counts.get("partial")
        and int(baseline_counts.get("scanned_files", 0))
        == int(baseline_counts.get("discovered_files", 0))
        and int(baseline_counts.get("traversal_errors", 0)) == 0
        and int(baseline_counts.get("unfollowed_symlink_dirs", 0)) == 0
    )

    archive_observations = int(
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
        archive_observations
        == int(archive_counts.get("scanned", 0))
        + int(archive_counts.get("unreadable", 0))
        and archive_members == int(archive_counts.get("members", 0))
    )
    archive_traversal_complete = (
        not archive_counts.get("partial")
        and archive_observations == int(archive_counts.get("discovered_archives", 0))
        and int(archive_counts.get("traversal_errors", 0)) == 0
        and int(archive_counts.get("unfollowed_symlink_dirs", 0)) == 0
    )

    archive_only = int(
        conn.execute(
            """SELECT COUNT(DISTINCT m.member_sha256)
               FROM archive_members m JOIN archive_observations o USING(archive_obs_id)
               WHERE o.corpus_run_id=? AND m.is_screenshot=1 AND m.state='scanned'
                 AND m.member_sha256 IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM screenshots s WHERE s.sha256=m.member_sha256
                 )""",
            (corpus_run_id,),
        ).fetchone()[0]
    )

    missing_canonical = int(state_counts.get("missing_on_disk", 0))
    hash_mismatch = int(state_counts.get("hash_mismatch", 0))
    unreadable_manifestations = int(state_counts.get("unreadable", 0))
    unreadable_archives = int(archive_counts.get("unreadable", 0))
    unreadable_members = int(archive_counts.get("member_unreadable", 0))
    structural_residue = (
        logical_sha_duplicate_rows
        + (0 if baseline_closed else 1)
        + (0 if archive_closed else 1)
        + (0 if baseline_traversal_complete else 1)
        + (0 if archive_traversal_complete else 1)
    )
    unexplained_residue = (
        hash_mismatch
        + unreadable_manifestations
        + unreadable_archives
        + unreadable_members
        + structural_residue
    )
    partial = bool(baseline_counts.get("partial") or archive_counts.get("partial"))

    if partial:
        status = "OPEN_PARTIAL"
    elif unexplained_residue:
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
        "historical_missing_source_manifestations": missing_canonical,
        "baseline_arithmetic_closed": baseline_closed,
        "baseline_traversal_complete": baseline_traversal_complete,
        "archive_arithmetic_closed": archive_closed,
        "archive_traversal_complete": archive_traversal_complete,
        "unexplained_residue": unexplained_residue,
    }
    corpus_digest = _corpus_digest(conn, corpus_run_id, reconciliation)

    calibration = conn.execute(
        """SELECT status, bound_corpus_digest FROM pipeline_certifications
           WHERE gate_name=?""",
        (OCR_GATE,),
    ).fetchone()
    calibration_pass = bool(
        calibration and calibration[0] == "PASS" and calibration[1] == corpus_digest
    )
    mass_ocr_ready = (
        status == "PASS"
        and archive_only == 0
        and missing_canonical == 0
        and calibration_pass
    )
    certification = {
        "protocol": CORPUS_PROTOCOL,
        "scope": "RLSM_SCREENSHOT_CORPUS_INGEST",
        "status": status,
        "corpus_digest": corpus_digest,
        "counts": counts,
        "gates": {
            "corpus_freeze_pass": status == "PASS",
            "zero_unexplained_ingest_residue": unexplained_residue == 0,
            "logical_sha_uniqueness": logical_sha_duplicate_rows == 0,
            "baseline_arithmetic_closed": baseline_closed,
            "baseline_traversal_complete": baseline_traversal_complete,
            "archive_arithmetic_closed": archive_closed,
            "archive_traversal_complete": archive_traversal_complete,
            "archive_only_screenshot_payloads_zero": archive_only == 0,
            "canonical_missing_sources_zero": missing_canonical == 0,
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
        """SELECT status, bound_corpus_digest FROM pipeline_certifications
           WHERE gate_name=?""",
        (OCR_GATE,),
    ).fetchone()
    now = utc_now()
    if row and row[0] == "PASS" and row[1] != corpus_digest:
        conn.execute(
            """UPDATE pipeline_certifications
               SET status='OPEN', bound_corpus_digest=?, evidence_sha256=NULL,
                   decided_at=?,
                   detail='corpus digest changed; empirical calibration must be re-bound'
               WHERE gate_name=?""",
            (corpus_digest, now, OCR_GATE),
        )
    elif row is None:
        conn.execute(
            """INSERT INTO pipeline_certifications
               (gate_name, status, bound_corpus_digest, evidence_sha256, decided_at, detail)
               VALUES (?, 'OPEN', ?, NULL, ?,
                       'empirical OCR calibration has not yet been executed')""",
            (OCR_GATE, corpus_digest, now),
        )


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_artifacts(
    conn: sqlite3.Connection,
    *,
    corpus_run_id: int,
    certification: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus_fields = [
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
        "ingest_status",
        "ingest_error",
        "ocr_status",
        "source_availability",
    ]
    corpus_rows = [
        dict(zip(corpus_fields, row, strict=True))
        for row in conn.execute(
            """SELECT screenshot_id, sha256, filename, rel_path, month_bucket,
                      filename_ts, ext, size_bytes, width, height, phash,
                      ingest_status, ingest_error, ocr_status, source_availability
               FROM screenshots ORDER BY screenshot_id"""
        )
    ]
    _write_csv(output_dir / "01_corpus_manifest.csv", corpus_rows, corpus_fields)

    member_fields = [
        "archive_locator",
        "outer_sha256",
        "member_ordinal",
        "member_path",
        "uncompressed_size",
        "compressed_size",
        "member_sha256",
        "is_screenshot",
        "state",
        "error",
    ]
    member_rows = [
        dict(zip(member_fields, row, strict=True))
        for row in conn.execute(
            """SELECT a.locator, o.outer_sha256, m.member_ordinal, m.member_path,
                      m.uncompressed_size, m.compressed_size, m.member_sha256,
                      m.is_screenshot, m.state, m.error
               FROM archive_members m
               JOIN archive_observations o USING(archive_obs_id)
               JOIN source_archives a USING(archive_id)
               WHERE o.corpus_run_id=? ORDER BY a.locator, m.member_ordinal""",
            (corpus_run_id,),
        )
    ]
    _write_csv(
        output_dir / "02_archive_member_manifest.csv", member_rows, member_fields
    )

    reconciliation_fields = [
        "manifestation_id",
        "source_kind",
        "rel_path",
        "screenshot_id",
        "observed_sha256",
        "expected_sha256",
        "size_bytes",
        "state",
        "detail",
    ]
    reconciliation_rows = _reconciliation_rows(conn, corpus_run_id)
    _write_csv(
        output_dir / "03_db_filesystem_reconciliation.csv",
        reconciliation_rows,
        reconciliation_fields,
    )

    duplicate_rows = []
    duplicate_query = conn.execute(
        """SELECT o.observed_sha256, COUNT(*)
           FROM source_manifestation_observations o
           JOIN source_manifestations m USING(manifestation_id)
           WHERE o.corpus_run_id=? AND m.source_kind='baseline_file'
             AND o.observed_sha256 IS NOT NULL
           GROUP BY o.observed_sha256 HAVING COUNT(*) > 1
           ORDER BY o.observed_sha256""",
        (corpus_run_id,),
    )
    for digest, count in duplicate_query:
        paths = [
            row[0]
            for row in conn.execute(
                """SELECT m.rel_path FROM source_manifestation_observations o
                   JOIN source_manifestations m USING(manifestation_id)
                   WHERE o.corpus_run_id=? AND m.source_kind='baseline_file'
                     AND o.observed_sha256=? ORDER BY m.rel_path""",
                (corpus_run_id, digest),
            )
        ]
        duplicate_rows.append(
            {
                "sha256": digest,
                "manifestation_count": count,
                "manifestation_paths_json": stable_json(paths),
            }
        )
    _write_csv(
        output_dir / "04_duplicate_groups.csv",
        duplicate_rows,
        ["sha256", "manifestation_count", "manifestation_paths_json"],
    )

    equivalence_fields = [
        "left_archive",
        "right_archive",
        "classification",
        "detail_json",
    ]
    equivalence_rows = [
        dict(zip(equivalence_fields, row, strict=True))
        for row in conn.execute(
            """SELECT la.locator, ra.locator, e.classification, e.detail_json
               FROM archive_equivalence e
               JOIN source_archives la ON la.archive_id=e.left_archive_id
               JOIN source_archives ra ON ra.archive_id=e.right_archive_id
               WHERE e.corpus_run_id=? ORDER BY la.locator, ra.locator""",
            (corpus_run_id,),
        )
    ]
    _write_csv(
        output_dir / "04_archive_equivalence.csv",
        equivalence_rows,
        equivalence_fields,
    )

    (output_dir / "05_ingest_certification.json").write_text(
        json.dumps(certification, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _refresh_readiness_after_calibration_invalidation(
    conn: sqlite3.Connection, certification: dict, corpus_digest: str
) -> None:
    calibration = conn.execute(
        """SELECT status, bound_corpus_digest FROM pipeline_certifications
           WHERE gate_name=?""",
        (OCR_GATE,),
    ).fetchone()
    calibration_pass = bool(
        calibration and calibration[0] == "PASS" and calibration[1] == corpus_digest
    )
    gates = certification["gates"]
    gates["ocr_calibration_bound_pass"] = calibration_pass
    gates["mass_ocr_ready"] = bool(
        certification["status"] == "PASS"
        and certification["counts"]["archive_only_screenshot_payloads"] == 0
        and certification["counts"]["historical_missing_source_manifestations"] == 0
        and calibration_pass
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

    roots = [Path(root) for root in archive_roots]
    started_at = utc_now()
    cursor = conn.execute(
        """INSERT INTO corpus_freeze_runs
           (protocol, started_at, status, baseline_root, archive_roots_json)
           VALUES (?, ?, 'IN_PROGRESS', ?, ?)""",
        (
            CORPUS_PROTOCOL,
            started_at,
            _locator(baseline, repo_root),
            stable_json([_locator(root, repo_root) for root in roots]),
        ),
    )
    corpus_run_id = int(cursor.lastrowid)
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
        _refresh_readiness_after_calibration_invalidation(
            conn, certification, corpus_digest
        )
        conn.execute(
            """UPDATE corpus_freeze_runs
               SET ended_at=?, status=?, corpus_digest=?, counts_json=?,
                   certification_json=?
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
            """UPDATE corpus_freeze_runs
               SET ended_at=?, status='FAIL' WHERE corpus_run_id=?""",
            (utc_now(), corpus_run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze and reconcile the RLSM screenshot corpus."
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--archive-root", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--budget-sec",
        type=float,
        default=0,
        help=(
            "Optional wall-clock cap. A cap that truncates traversal yields "
            "OPEN_PARTIAL, never PASS."
        ),
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
