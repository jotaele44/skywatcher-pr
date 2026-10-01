"""Persistent, fail-closed screenshot processing for interactive Skywatcher intake.

This module is deliberately an orchestrator. It reuses RLSM inventory/OCR/parsing
and the existing track vectorizer while keeping screenshot observations separate
from canonical flight identity. Jobs are restartable and durable in a small
runtime SQLite database; source bytes are stored under data/screenshot_processing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JOB_DB = REPO_ROOT / "data" / "screenshot_processing" / "jobs.sqlite3"
DEFAULT_JOB_ROOT = REPO_ROOT / "data" / "screenshot_processing" / "jobs"
DEFAULT_RLSM_DB = REPO_ROOT / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_CORPUS_DB = Path(
    os.environ.get("SKYWATCHER_DB", str(REPO_ROOT / "data" / "skywatcher.db"))
)
RLSM_SCHEMA = REPO_ROOT / "data" / "rlsm" / "schema.sql"

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".heic", ".heif"}
)
CONTAINER_EXTENSIONS = frozenset({".zip", ".pdf"})
MAX_SOURCE_BYTES = int(
    os.environ.get("SKYWATCHER_SCREENSHOT_SOURCE_MAX_BYTES", str(64 * 1024 * 1024))
)
MAX_JOB_BYTES = int(
    os.environ.get("SKYWATCHER_SCREENSHOT_JOB_MAX_BYTES", str(256 * 1024 * 1024))
)
MAX_ARCHIVE_MEMBERS = int(os.environ.get("SKYWATCHER_SCREENSHOT_MAX_ARCHIVE_MEMBERS", "1000"))
MAX_ARCHIVE_EXPANDED_BYTES = int(
    os.environ.get("SKYWATCHER_SCREENSHOT_MAX_ARCHIVE_BYTES", str(512 * 1024 * 1024))
)

_ALLOWED_JOB_STATUS = {
    "STAGED",
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "COMPLETED",
    "FAILED",
    "CANCELED",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="skywatcher-screenshot")
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()


class ScreenshotProcessingError(RuntimeError):
    """Raised when an interactive screenshot job violates its contract."""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(name: str, fallback: str = "upload.bin") -> str:
    raw = Path(str(name or "")).name.strip()
    cleaned = _SAFE_NAME.sub("_", raw).strip(" .")
    return (cleaned or fallback)[:180]


def _decode_base64(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ScreenshotProcessingError("content_base64 is required")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ScreenshotProcessingError("invalid base64 upload payload") from exc


def _month_bucket(timestamp: str | None) -> str | None:
    if isinstance(timestamp, str) and re.match(r"^\d{4}-\d{2}", timestamp):
        return timestamp[:7]
    return None


def _job_progress(stage: str, done: int, total: int) -> float:
    windows = {
        "inventory": (0.0, 0.20),
        "ocr": (0.20, 0.58),
        "extract": (0.58, 0.78),
        "trajectory": (0.78, 0.88),
        "reconcile": (0.88, 0.97),
        "finalize": (0.97, 1.00),
    }
    start, end = windows.get(stage, (0.0, 1.0))
    fraction = 1.0 if total <= 0 else max(0.0, min(1.0, done / total))
    return round(start + ((end - start) * fraction), 4)


def _default_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    supplied = settings or {}
    defaults: dict[str, Any] = {
        "source_family": "auto",
        "ocr": True,
        "vision_assist": "low_confidence_only",
        "track_vectorization": True,
        "georeference": True,
        "match_existing_flights": True,
        "auto_commit": False,
        "retain_uploads": True,
        "candidate_time_window_minutes": 90,
    }
    defaults.update(supplied)
    # External vision must never be silently enabled by a malformed setting.
    if defaults["vision_assist"] not in {"disabled", "low_confidence_only", "comprehensive"}:
        raise ScreenshotProcessingError("unsupported vision_assist setting")
    defaults["auto_commit"] = False
    return defaults


class ScreenshotJobStore:
    """Durable job ledger and staged-source store."""

    def __init__(
        self,
        db_path: Path = DEFAULT_JOB_DB,
        job_root: Path = DEFAULT_JOB_ROOT,
        rlsm_db: Path = DEFAULT_RLSM_DB,
        corpus_db: Path = DEFAULT_CORPUS_DB,
    ) -> None:
        self.db_path = Path(db_path)
        self.job_root = Path(job_root)
        self.rlsm_db = Path(rlsm_db)
        self.corpus_db = Path(corpus_db)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS screenshot_processing_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_count INTEGER NOT NULL DEFAULT 0,
                manifestation_count INTEGER NOT NULL DEFAULT 0,
                processable_count INTEGER NOT NULL DEFAULT 0,
                processed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS screenshot_processing_sources (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES screenshot_processing_jobs(job_id)
                    ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                source_name_raw TEXT NOT NULL,
                stored_source_rel_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                source_kind TEXT NOT NULL,
                member_count INTEGER NOT NULL DEFAULT 0,
                processable_count INTEGER NOT NULL DEFAULT 0,
                excluded_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                detail TEXT,
                UNIQUE(job_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS screenshot_processing_files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES screenshot_processing_jobs(job_id)
                    ON DELETE CASCADE,
                source_id INTEGER NOT NULL REFERENCES screenshot_processing_sources(source_id)
                    ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                source_locator TEXT NOT NULL,
                source_member TEXT,
                page_number INTEGER,
                media_kind TEXT NOT NULL,
                source_name_raw TEXT NOT NULL,
                stored_rel_path TEXT,
                payload_sha256 TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                screenshot_id INTEGER,
                exact_duplicate INTEGER NOT NULL DEFAULT 0,
                within_job_duplicate_of INTEGER,
                ocr_status TEXT,
                extraction_status TEXT,
                extracted_fields_json TEXT,
                extraction_confidence REAL,
                track_features_json TEXT,
                georeference_json TEXT,
                reconciliation_status TEXT,
                candidate_matches_json TEXT,
                contradictions_json TEXT,
                unresolved_json TEXT,
                committed_corpus_record_id INTEGER,
                error TEXT,
                UNIQUE(job_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS screenshot_processing_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES screenshot_processing_jobs(job_id)
                    ON DELETE CASCADE,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_screenshot_processing_files_job
                ON screenshot_processing_files(job_id, ordinal);
            CREATE INDEX IF NOT EXISTS ix_screenshot_processing_files_sha
                ON screenshot_processing_files(payload_sha256);
            CREATE INDEX IF NOT EXISTS ix_screenshot_processing_events_job
                ON screenshot_processing_events(job_id, event_id);
            """
        )
        conn.commit()

    def _event(self, conn: sqlite3.Connection, job_id: str, stage: str, status: str, message: str) -> None:
        conn.execute(
            """
            INSERT INTO screenshot_processing_events
                (job_id, stage, status, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, stage, status, message, _utc_now()),
        )

    def _update_job(self, conn: sqlite3.Connection, job_id: str, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = _utc_now()
        columns = ", ".join(f"{key}=?" for key in values)
        conn.execute(
            f"UPDATE screenshot_processing_jobs SET {columns} WHERE job_id=?",
            (*values.values(), job_id),
        )

    def create_job(self, uploads: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(uploads, list) or not uploads:
            raise ScreenshotProcessingError("at least one upload is required")

        parsed: list[tuple[str, bytes]] = []
        total_bytes = 0
        for item in uploads:
            if not isinstance(item, dict):
                raise ScreenshotProcessingError("each upload must be an object")
            name = str(item.get("name") or "upload.bin")
            payload = _decode_base64(item.get("content_base64"))
            if len(payload) > MAX_SOURCE_BYTES:
                raise ScreenshotProcessingError(
                    f"{name}: source exceeds {MAX_SOURCE_BYTES} byte limit"
                )
            total_bytes += len(payload)
            if total_bytes > MAX_JOB_BYTES:
                raise ScreenshotProcessingError(
                    f"job exceeds {MAX_JOB_BYTES} byte aggregate limit"
                )
            parsed.append((name, payload))

        job_id = str(uuid.uuid4())
        job_dir = self.job_root / job_id
        source_dir = job_dir / "sources"
        input_dir = job_dir / "inputs"
        source_dir.mkdir(parents=True, exist_ok=False)
        input_dir.mkdir(parents=True, exist_ok=False)

        resolved_settings = _default_settings(settings)
        now = _utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO screenshot_processing_jobs
                    (job_id, status, stage, progress, settings_json, created_at, updated_at)
                VALUES (?, 'STAGED', 'upload', 0, ?, ?, ?)
                """,
                (job_id, _canonical_json(resolved_settings), now, now),
            )

            manifestation_ordinal = 0
            seen_payloads: dict[str, int] = {}
            total_processable = total_manifestations = total_excluded = 0
            for source_ordinal, (raw_name, payload) in enumerate(parsed, 1):
                safe_name = _safe_filename(raw_name, f"upload-{source_ordinal}.bin")
                source_path = source_dir / f"{source_ordinal:04d}_{safe_name}"
                source_path.write_bytes(payload)
                source_sha = _sha256(payload)
                source_kind = self._source_kind(raw_name)
                source_cursor = conn.execute(
                    """
                    INSERT INTO screenshot_processing_sources
                        (job_id, ordinal, source_name_raw, stored_source_rel_path,
                         source_sha256, size_bytes, source_kind, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'STAGED')
                    """,
                    (
                        job_id,
                        source_ordinal,
                        raw_name,
                        source_path.relative_to(REPO_ROOT).as_posix(),
                        source_sha,
                        len(payload),
                        source_kind,
                    ),
                )
                source_id = int(source_cursor.lastrowid)

                manifestations = self._expand_source(raw_name, payload)
                source_processable = source_excluded = 0
                for manifest in manifestations:
                    manifestation_ordinal += 1
                    total_manifestations += 1
                    processable = manifest["media_kind"] == "native_image"
                    stored_rel_path = None
                    payload_sha = None
                    size_bytes = int(manifest.get("size_bytes") or 0)
                    duplicate_of = None
                    if processable:
                        source_processable += 1
                        total_processable += 1
                        visual_bytes = manifest["bytes"]
                        payload_sha = _sha256(visual_bytes)
                        ext = str(manifest.get("extension") or ".png").lower()
                        if ext not in IMAGE_EXTENSIONS:
                            ext = ".png"
                        staged = input_dir / f"{manifestation_ordinal:06d}_{payload_sha[:16]}{ext}"
                        staged.write_bytes(visual_bytes)
                        stored_rel_path = staged.relative_to(REPO_ROOT).as_posix()
                        duplicate_of = seen_payloads.get(payload_sha)
                        if duplicate_of is None:
                            seen_payloads[payload_sha] = manifestation_ordinal
                    else:
                        source_excluded += 1
                        total_excluded += 1

                    conn.execute(
                        """
                        INSERT INTO screenshot_processing_files
                            (job_id, source_id, ordinal, source_locator, source_member,
                             page_number, media_kind, source_name_raw, stored_rel_path,
                             payload_sha256, size_bytes, status, within_job_duplicate_of,
                             unresolved_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            source_id,
                            manifestation_ordinal,
                            manifest["source_locator"],
                            manifest.get("source_member"),
                            manifest.get("page_number"),
                            manifest["media_kind"],
                            raw_name,
                            stored_rel_path,
                            payload_sha,
                            size_bytes,
                            "STAGED" if processable else "EXCLUDED",
                            duplicate_of,
                            _canonical_json(manifest.get("unresolved") or []),
                        ),
                    )

                conn.execute(
                    """
                    UPDATE screenshot_processing_sources
                    SET member_count=?, processable_count=?, excluded_count=?,
                        status=?, detail=?
                    WHERE source_id=?
                    """,
                    (
                        len(manifestations),
                        source_processable,
                        source_excluded,
                        "STAGED" if source_processable else "UNRESOLVED",
                        None if source_processable else "no processable visual manifestations",
                        source_id,
                    ),
                )

            self._update_job(
                conn,
                job_id,
                source_count=len(parsed),
                manifestation_count=total_manifestations,
                processable_count=total_processable,
                status="STAGED" if total_processable else "FAILED",
                stage="ready" if total_processable else "inventory",
                error=None if total_processable else "no processable screenshots were found",
            )
            self._event(
                conn,
                job_id,
                "upload",
                "PASS" if total_processable else "FAIL",
                (
                    f"{len(parsed)} source(s); {total_manifestations} manifestation(s); "
                    f"{total_processable} processable; {total_excluded} excluded"
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_job(job_id)

    @staticmethod
    def _source_kind(name: str) -> str:
        ext = Path(name).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return "native_image"
        if ext == ".zip":
            return "archive"
        if ext == ".pdf":
            return "pdf"
        return "unsupported"

    def _expand_source(self, name: str, payload: bytes) -> list[dict[str, Any]]:
        ext = Path(name).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return [
                {
                    "source_locator": name,
                    "source_member": None,
                    "page_number": None,
                    "media_kind": "native_image",
                    "extension": ext,
                    "size_bytes": len(payload),
                    "bytes": payload,
                    "unresolved": [],
                }
            ]
        if ext == ".zip":
            return self._expand_zip(name, payload)
        if ext == ".pdf":
            return self._expand_pdf(name, payload)
        return [
            {
                "source_locator": name,
                "source_member": None,
                "page_number": None,
                "media_kind": "unsupported",
                "size_bytes": len(payload),
                "unresolved": ["unsupported source type"],
            }
        ]

    @staticmethod
    def _expand_zip(name: str, payload: bytes) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        expanded = 0
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile:
            return [
                {
                    "source_locator": name,
                    "media_kind": "unsupported",
                    "size_bytes": len(payload),
                    "unresolved": ["invalid ZIP archive"],
                }
            ]
        with archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise ScreenshotProcessingError(
                    f"{name}: archive member count exceeds {MAX_ARCHIVE_MEMBERS}"
                )
            for info in infos:
                expanded += int(info.file_size)
                if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ScreenshotProcessingError(
                        f"{name}: expanded archive exceeds {MAX_ARCHIVE_EXPANDED_BYTES} bytes"
                    )
                member_ext = Path(info.filename).suffix.lower()
                locator = f"{name}::{info.filename}"
                if member_ext not in IMAGE_EXTENSIONS:
                    rows.append(
                        {
                            "source_locator": locator,
                            "source_member": info.filename,
                            "page_number": None,
                            "media_kind": "unsupported_archive_member",
                            "size_bytes": int(info.file_size),
                            "unresolved": ["archive member is not a supported image"],
                        }
                    )
                    continue
                try:
                    member_bytes = archive.read(info)
                except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
                    rows.append(
                        {
                            "source_locator": locator,
                            "source_member": info.filename,
                            "page_number": None,
                            "media_kind": "unreadable_archive_member",
                            "size_bytes": int(info.file_size),
                            "unresolved": [f"archive member unreadable: {type(exc).__name__}"],
                        }
                    )
                    continue
                rows.append(
                    {
                        "source_locator": locator,
                        "source_member": info.filename,
                        "page_number": None,
                        "media_kind": "native_image",
                        "extension": member_ext,
                        "size_bytes": len(member_bytes),
                        "bytes": member_bytes,
                        "unresolved": [],
                    }
                )
        return rows or [
            {
                "source_locator": name,
                "media_kind": "unsupported",
                "size_bytes": len(payload),
                "unresolved": ["empty ZIP archive"],
            }
        ]

    @staticmethod
    def _expand_pdf(name: str, payload: bytes) -> list[dict[str, Any]]:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return [
                {
                    "source_locator": name,
                    "media_kind": "pdf_unrendered",
                    "size_bytes": len(payload),
                    "unresolved": ["PyMuPDF unavailable; PDF pages not rendered"],
                }
            ]
        try:
            document = fitz.open(stream=payload, filetype="pdf")
        except Exception as exc:
            return [
                {
                    "source_locator": name,
                    "media_kind": "pdf_unreadable",
                    "size_bytes": len(payload),
                    "unresolved": [f"PDF unreadable: {type(exc).__name__}"],
                }
            ]
        rows: list[dict[str, Any]] = []
        try:
            for index, page in enumerate(document, 1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                rendered = pix.tobytes("png")
                rows.append(
                    {
                        "source_locator": f"{name}::page-{index}",
                        "source_member": None,
                        "page_number": index,
                        "media_kind": "native_image",
                        "extension": ".png",
                        "size_bytes": len(rendered),
                        "bytes": rendered,
                        "unresolved": [
                            "PDF page rendering is a distinct manifestation from PDF byte identity"
                        ],
                    }
                )
        finally:
            document.close()
        return rows

    def list_jobs(self, limit: int = 25) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM screenshot_processing_jobs
                ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [self._job_dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["settings"] = json.loads(result.pop("settings_json"))
        for key in ("paused", "cancel_requested"):
            result[key] = bool(result[key])
        return result

    def get_job(self, job_id: str, *, include_files: bool = True) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM screenshot_processing_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            result = self._job_dict(row)
            if include_files:
                files = conn.execute(
                    """
                    SELECT * FROM screenshot_processing_files
                    WHERE job_id=? ORDER BY ordinal
                    """,
                    (job_id,),
                ).fetchall()
                result["files"] = [self._file_dict(item) for item in files]
                events = conn.execute(
                    """
                    SELECT event_id, stage, status, message, created_at
                    FROM screenshot_processing_events
                    WHERE job_id=? ORDER BY event_id DESC LIMIT 100
                    """,
                    (job_id,),
                ).fetchall()
                result["events"] = [dict(item) for item in reversed(events)]
            return result
        finally:
            conn.close()

    @staticmethod
    def _file_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in (
            "extracted_fields_json",
            "track_features_json",
            "georeference_json",
            "candidate_matches_json",
            "contradictions_json",
            "unresolved_json",
        ):
            value = result.pop(key)
            result[key.removesuffix("_json")] = json.loads(value) if value else (
                [] if key in {"candidate_matches_json", "contradictions_json", "unresolved_json"} else None
            )
        result["exact_duplicate"] = bool(result["exact_duplicate"])
        return result

    def set_paused(self, job_id: str, paused: bool) -> dict[str, Any]:
        conn = self._connect()
        try:
            self._update_job(
                conn,
                job_id,
                paused=1 if paused else 0,
                status="PAUSED" if paused else "RUNNING",
            )
            self._event(conn, job_id, "control", "PASS", "pause requested" if paused else "resume requested")
            conn.commit()
        finally:
            conn.close()
        return self.get_job(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            self._update_job(conn, job_id, cancel_requested=1)
            self._event(conn, job_id, "control", "PASS", "cancel requested")
            conn.commit()
        finally:
            conn.close()
        return self.get_job(job_id)

    def submit(self, job_id: str) -> dict[str, Any]:
        current = self.get_job(job_id, include_files=False)
        if current["status"] not in {"STAGED", "PAUSED", "FAILED"}:
            return current
        with _ACTIVE_LOCK:
            if job_id in _ACTIVE:
                return current
            _ACTIVE.add(job_id)
        conn = self._connect()
        try:
            self._update_job(
                conn,
                job_id,
                status="QUEUED",
                stage="inventory",
                error=None,
                cancel_requested=0,
                paused=0,
            )
            self._event(conn, job_id, "inventory", "OPEN", "job queued")
            conn.commit()
        finally:
            conn.close()
        _EXECUTOR.submit(self._worker_guard, job_id)
        return self.get_job(job_id)

    def _worker_guard(self, job_id: str) -> None:
        try:
            self._execute(job_id)
        except Exception as exc:
            conn = self._connect()
            try:
                self._update_job(
                    conn,
                    job_id,
                    status="FAILED",
                    stage="failed",
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
                self._event(conn, job_id, "failed", "FAIL", f"{type(exc).__name__}: {exc}"[:1000])
                conn.commit()
            finally:
                conn.close()
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)

    def _check_control(self, conn: sqlite3.Connection, job_id: str) -> bool:
        while True:
            row = conn.execute(
                "SELECT paused, cancel_requested FROM screenshot_processing_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                return False
            if row["cancel_requested"]:
                self._update_job(conn, job_id, status="CANCELED", stage="canceled")
                self._event(conn, job_id, "control", "PASS", "job canceled")
                conn.commit()
                return False
            if not row["paused"]:
                return True
            self._update_job(conn, job_id, status="PAUSED")
            conn.commit()
            time.sleep(0.25)

    def _ensure_rlsm(self) -> sqlite3.Connection:
        if not RLSM_SCHEMA.is_file():
            raise ScreenshotProcessingError("RLSM schema is missing")
        self.rlsm_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.rlsm_db), timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.executescript(RLSM_SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        return conn

    def _execute(self, job_id: str) -> None:
        job_conn = self._connect()
        rlsm_conn = self._ensure_rlsm()
        try:
            self._update_job(job_conn, job_id, status="RUNNING", stage="inventory", progress=0.0)
            self._event(job_conn, job_id, "inventory", "OPEN", "binding staged manifestations to RLSM")
            job_conn.commit()
            files = job_conn.execute(
                """
                SELECT * FROM screenshot_processing_files
                WHERE job_id=? AND media_kind='native_image'
                ORDER BY ordinal
                """,
                (job_id,),
            ).fetchall()
            total = len(files)
            if total == 0:
                raise ScreenshotProcessingError("job contains no processable image manifestations")

            from scripts import rlsm_inventory

            inv_cursor = rlsm_conn.execute(
                """
                INSERT INTO processing_runs
                    (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
                VALUES ('interactive_inventory', ?, 'in_progress', ?, 0, 0, ?)
                """,
                (_utc_now(), total, _canonical_json({"job_id": job_id})),
            )
            inv_run_id = int(inv_cursor.lastrowid)
            rlsm_conn.commit()

            processed_inventory = failed_inventory = 0
            for index, row in enumerate(files, 1):
                if not self._check_control(job_conn, job_id):
                    return
                rel_path = str(row["stored_rel_path"])
                full_path = REPO_ROOT / rel_path
                try:
                    outcome = rlsm_inventory._ingest_file(
                        rlsm_conn,
                        full_path,
                        rel_path,
                        inv_run_id,
                    )
                    if outcome.get("ok"):
                        rlsm_inventory._record_source_manifestation(
                            rlsm_conn,
                            full_path,
                            rel_path,
                            outcome,
                        )
                        screenshot_id = outcome.get("existing_id")
                        if screenshot_id is None:
                            existing = rlsm_conn.execute(
                                "SELECT screenshot_id FROM screenshots WHERE sha256=?",
                                (row["payload_sha256"],),
                            ).fetchone()
                            screenshot_id = existing[0] if existing else None
                        exact_duplicate = 1 if outcome.get("dup_sha") else 0
                        job_conn.execute(
                            """
                            UPDATE screenshot_processing_files
                            SET screenshot_id=?, exact_duplicate=?, status='INVENTORIED'
                            WHERE file_id=?
                            """,
                            (screenshot_id, exact_duplicate, row["file_id"]),
                        )
                        processed_inventory += 1
                    else:
                        job_conn.execute(
                            """
                            UPDATE screenshot_processing_files
                            SET status='FAILED', error=?
                            WHERE file_id=?
                            """,
                            (str(outcome.get("reason") or "inventory failure"), row["file_id"]),
                        )
                        failed_inventory += 1
                except Exception as exc:
                    job_conn.execute(
                        """
                        UPDATE screenshot_processing_files
                        SET status='FAILED', error=?
                        WHERE file_id=?
                        """,
                        (f"{type(exc).__name__}: {exc}"[:500], row["file_id"]),
                    )
                    failed_inventory += 1
                self._update_job(
                    job_conn,
                    job_id,
                    progress=_job_progress("inventory", index, total),
                    processed_count=index,
                    failed_count=failed_inventory,
                )
                job_conn.commit()

            rlsm_conn.execute(
                """
                UPDATE processing_runs
                SET ended_at=?, status='completed', n_processed=?, n_failed=?
                WHERE run_id=?
                """,
                (_utc_now(), processed_inventory, failed_inventory, inv_run_id),
            )
            rlsm_conn.commit()
            self._event(
                job_conn,
                job_id,
                "inventory",
                "PASS" if failed_inventory == 0 else "PROVISIONAL",
                f"{processed_inventory} inventoried; {failed_inventory} failed",
            )
            job_conn.commit()

            self._run_ocr(job_conn, rlsm_conn, job_id)
            self._run_extract(job_conn, rlsm_conn, job_id)
            self._run_trajectory(job_conn, rlsm_conn, job_id)
            self._run_reconciliation(job_conn, job_id)

            self._update_job(
                job_conn,
                job_id,
                status="COMPLETED",
                stage="complete",
                progress=1.0,
            )
            self._event(
                job_conn,
                job_id,
                "finalize",
                "PASS",
                "processing completed; canonical flight identity remains unchanged",
            )
            job_conn.commit()
        finally:
            rlsm_conn.close()
            job_conn.close()

    def _run_ocr(self, job_conn: sqlite3.Connection, rlsm_conn: sqlite3.Connection, job_id: str) -> None:
        settings = self.get_job(job_id, include_files=False)["settings"]
        rows = job_conn.execute(
            """
            SELECT file_id, screenshot_id, stored_rel_path FROM screenshot_processing_files
            WHERE job_id=? AND screenshot_id IS NOT NULL AND status != 'FAILED'
            ORDER BY ordinal
            """,
            (job_id,),
        ).fetchall()
        total = len(rows)
        self._update_job(job_conn, job_id, stage="ocr")
        self._event(job_conn, job_id, "ocr", "OPEN", "OCR stage started")
        job_conn.commit()
        if not settings.get("ocr", True):
            for row in rows:
                job_conn.execute(
                    "UPDATE screenshot_processing_files SET ocr_status='SKIPPED' WHERE file_id=?",
                    (row["file_id"],),
                )
            self._event(job_conn, job_id, "ocr", "AUDIT_ONLY", "OCR disabled by job settings")
            job_conn.commit()
            return

        from fr24.rlsm_ocr import process_screenshot

        run_cursor = rlsm_conn.execute(
            """
            INSERT INTO processing_runs
                (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
            VALUES ('interactive_ocr', ?, 'in_progress', ?, 0, 0, ?)
            """,
            (_utc_now(), total, _canonical_json({"job_id": job_id})),
        )
        run_id = int(run_cursor.lastrowid)
        rlsm_conn.commit()
        ok = failed = 0
        handled_sids: set[int] = set()
        for index, row in enumerate(rows, 1):
            if not self._check_control(job_conn, job_id):
                return
            sid = int(row["screenshot_id"])
            current = rlsm_conn.execute(
                "SELECT ocr_status, rel_path FROM screenshots WHERE screenshot_id=?",
                (sid,),
            ).fetchone()
            if current is None:
                result = {"ok": False, "reason": "screenshot row missing"}
            elif sid in handled_sids or current["ocr_status"] in {"ok", "partial"}:
                result = {"ok": True, "reused": True}
            else:
                result = process_screenshot(
                    rlsm_conn,
                    sid,
                    str(current["rel_path"] or row["stored_rel_path"]),
                    run_id,
                )
                handled_sids.add(sid)
            if result.get("ok"):
                ok += 1
                state = "REUSED" if result.get("reused") else "PASS"
            else:
                failed += 1
                state = "FAIL"
            job_conn.execute(
                "UPDATE screenshot_processing_files SET ocr_status=? WHERE file_id=?",
                (state, row["file_id"]),
            )
            self._update_job(
                job_conn,
                job_id,
                progress=_job_progress("ocr", index, total),
                failed_count=failed,
            )
            job_conn.commit()
        rlsm_conn.execute(
            """
            UPDATE processing_runs
            SET ended_at=?, status='completed', n_processed=?, n_failed=?
            WHERE run_id=?
            """,
            (_utc_now(), ok, failed, run_id),
        )
        rlsm_conn.commit()
        self._event(
            job_conn,
            job_id,
            "ocr",
            "PASS" if failed == 0 else "PROVISIONAL",
            f"{ok} OCR-ready manifestation(s); {failed} failed",
        )
        job_conn.commit()

    def _run_extract(self, job_conn: sqlite3.Connection, rlsm_conn: sqlite3.Connection, job_id: str) -> None:
        settings = self.get_job(job_id, include_files=False)["settings"]
        self._update_job(job_conn, job_id, stage="extract")
        rows = job_conn.execute(
            """
            SELECT file_id, screenshot_id, unresolved_json FROM screenshot_processing_files
            WHERE job_id=? AND screenshot_id IS NOT NULL AND status != 'FAILED'
            ORDER BY ordinal
            """,
            (job_id,),
        ).fetchall()
        total = len(rows)
        from fr24.rlsm_extractors import _scan_text

        for index, row in enumerate(rows, 1):
            if not self._check_control(job_conn, job_id):
                return
            text_rows = rlsm_conn.execute(
                """
                SELECT zone, raw_text, confidence_mean FROM ocr_observations
                WHERE obs_id IN (
                    SELECT MAX(obs_id) FROM ocr_observations
                    WHERE screenshot_id=? GROUP BY zone
                )
                AND zone IN ('aircraft_card','top_bar','map_center','label_layer')
                """,
                (row["screenshot_id"],),
            ).fetchall()
            combined = " ".join(str(item["raw_text"] or "") for item in text_rows)
            confidences = [
                float(item["confidence_mean"])
                for item in text_rows
                if item["confidence_mean"] is not None
            ]
            fields = _scan_text(combined) if combined.strip() else {}
            confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
            unresolved = json.loads(row["unresolved_json"]) if row["unresolved_json"] else []
            if not fields:
                unresolved.append("no aircraft telemetry fields extracted")
            if "registration" not in fields and "callsign" not in fields:
                unresolved.append("aircraft identity fields unresolved")
            job_conn.execute(
                """
                UPDATE screenshot_processing_files
                SET extraction_status=?, extracted_fields_json=?,
                    extraction_confidence=?, unresolved_json=?
                WHERE file_id=?
                """,
                (
                    "PROVISIONAL" if fields else "UNRESOLVED",
                    _canonical_json(fields),
                    round(max(0.0, min(1.0, confidence)), 4),
                    _canonical_json(unresolved),
                    row["file_id"],
                ),
            )
            self._update_job(job_conn, job_id, progress=_job_progress("extract", index, total))
            job_conn.commit()
        self._event(
            job_conn,
            job_id,
            "extract",
            "PROVISIONAL",
            "field extraction complete; OCR-derived identity remains provisional",
        )
        if settings.get("vision_assist") != "disabled":
            self._event(
                job_conn,
                job_id,
                "vision_assist",
                "BLOCKED",
                "provider-neutral vision results may be ingested, but no external model is invoked automatically by this local processor",
            )
        job_conn.commit()

    def _run_trajectory(self, job_conn: sqlite3.Connection, rlsm_conn: sqlite3.Connection, job_id: str) -> None:
        settings = self.get_job(job_id, include_files=False)["settings"]
        rows = job_conn.execute(
            """
            SELECT file_id, screenshot_id, stored_rel_path
            FROM screenshot_processing_files
            WHERE job_id=? AND stored_rel_path IS NOT NULL AND status != 'FAILED'
            ORDER BY ordinal
            """,
            (job_id,),
        ).fetchall()
        total = len(rows)
        self._update_job(job_conn, job_id, stage="trajectory")
        job_conn.commit()
        if not settings.get("track_vectorization", True):
            self._event(job_conn, job_id, "trajectory", "AUDIT_ONLY", "track vectorization disabled")
            job_conn.commit()
            return

        try:
            from fr24.track_vectorizer import vectorize_image
        except Exception as exc:
            self._event(
                job_conn,
                job_id,
                "trajectory",
                "BLOCKED",
                f"track vectorizer unavailable: {type(exc).__name__}",
            )
            job_conn.commit()
            return

        for index, row in enumerate(rows, 1):
            if not self._check_control(job_conn, job_id):
                return
            track = None
            try:
                features = vectorize_image(str(REPO_ROOT / row["stored_rel_path"]))
                if features is not None:
                    track = {
                        "path_shape": features.path_shape,
                        "has_loop": bool(features.has_loop),
                        "has_orbit": bool(features.has_orbit),
                        "has_gap": bool(features.has_gap),
                        "track_length_px": features.track_length_px,
                        "bbox": list(features.bbox),
                        "confidence": features.confidence,
                        "evidence_type": "RENDERED_TRAIL",
                        "raw_trajectory": False,
                    }
            except Exception as exc:
                track = {"status": "UNRESOLVED", "error": f"{type(exc).__name__}: {exc}"[:300]}
            existing_georef = None
            if settings.get("georeference", True):
                try:
                    existing = rlsm_conn.execute(
                        """
                        SELECT status, method, fit_residual_m, estimated_error_m,
                               confidence, anchor_count, observed_at
                        FROM screenshot_georeferences
                        WHERE screenshot_id=? ORDER BY georef_id DESC LIMIT 1
                        """,
                        (row["screenshot_id"],),
                    ).fetchone()
                    if existing:
                        existing_georef = dict(existing)
                except sqlite3.Error:
                    existing_georef = None
            job_conn.execute(
                """
                UPDATE screenshot_processing_files
                SET track_features_json=?, georeference_json=?
                WHERE file_id=?
                """,
                (
                    _canonical_json(track) if track is not None else None,
                    _canonical_json(existing_georef) if existing_georef is not None else None,
                    row["file_id"],
                ),
            )
            self._update_job(job_conn, job_id, progress=_job_progress("trajectory", index, total))
            job_conn.commit()
        self._event(
            job_conn,
            job_id,
            "trajectory",
            "PROVISIONAL",
            "rendered-track observations captured; they are not raw trajectory",
        )
        job_conn.commit()

    def _run_reconciliation(self, job_conn: sqlite3.Connection, job_id: str) -> None:
        settings = self.get_job(job_id, include_files=False)["settings"]
        rows = job_conn.execute(
            """
            SELECT * FROM screenshot_processing_files
            WHERE job_id=? AND status != 'FAILED' AND media_kind='native_image'
            ORDER BY ordinal
            """,
            (job_id,),
        ).fetchall()
        total = len(rows)
        self._update_job(job_conn, job_id, stage="reconcile")
        job_conn.commit()
        if not settings.get("match_existing_flights", True):
            self._event(job_conn, job_id, "reconcile", "AUDIT_ONLY", "flight matching disabled")
            job_conn.commit()
            return
        if not self.corpus_db.is_file():
            for row in rows:
                job_conn.execute(
                    """
                    UPDATE screenshot_processing_files
                    SET reconciliation_status='BLOCKED', unresolved_json=?
                    WHERE file_id=?
                    """,
                    (_canonical_json(["canonical flight corpus database is unavailable"]), row["file_id"]),
                )
            self._event(job_conn, job_id, "reconcile", "BLOCKED", "canonical flight corpus database unavailable")
            job_conn.commit()
            return

        corpus = sqlite3.connect(str(self.corpus_db))
        corpus.row_factory = sqlite3.Row
        try:
            has_table = corpus.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='flight_corpus_records'
                """
            ).fetchone()
            if not has_table:
                self._event(job_conn, job_id, "reconcile", "BLOCKED", "flight_corpus_records table unavailable")
                job_conn.commit()
                return
            window_minutes = int(settings.get("candidate_time_window_minutes") or 90)
            for index, row in enumerate(rows, 1):
                if not self._check_control(job_conn, job_id):
                    return
                fields = json.loads(row["extracted_fields_json"]) if row["extracted_fields_json"] else {}
                candidates: list[dict[str, Any]] = []
                callsign = fields.get("callsign")
                if callsign:
                    candidate_rows = corpus.execute(
                        """
                        SELECT corpus_record_id, corpus_uid, snapshot_id,
                               source_flight_id_raw, callsign_raw,
                               start_time_utc, end_time_utc, identity_status
                        FROM flight_corpus_records
                        WHERE UPPER(TRIM(callsign_raw))=UPPER(TRIM(?))
                        ORDER BY start_time_utc DESC
                        LIMIT 100
                        """,
                        (callsign,),
                    ).fetchall()
                    for candidate in candidate_rows:
                        candidates.append(
                            {
                                **dict(candidate),
                                "relationship": "CANDIDATE_NOT_IDENTITY",
                                "basis": ["EXACT_CALLSIGN"],
                                "time_window_minutes": window_minutes,
                            }
                        )
                status = "CANDIDATE_NOT_IDENTITY" if candidates else "UNRESOLVED"
                contradictions: list[dict[str, Any]] = []
                if len(candidates) > 1:
                    contradictions.append(
                        {
                            "class": "IDENTITY",
                            "state": "UNRESOLVED",
                            "detail": f"{len(candidates)} equal-evidence corpus candidates",
                        }
                    )
                job_conn.execute(
                    """
                    UPDATE screenshot_processing_files
                    SET reconciliation_status=?, candidate_matches_json=?,
                        contradictions_json=?
                    WHERE file_id=?
                    """,
                    (
                        status,
                        _canonical_json(candidates),
                        _canonical_json(contradictions),
                        row["file_id"],
                    ),
                )
                self._update_job(job_conn, job_id, progress=_job_progress("reconcile", index, total))
                job_conn.commit()
        finally:
            corpus.close()
        review_count = job_conn.execute(
            """
            SELECT COUNT(*) AS n FROM screenshot_processing_files
            WHERE job_id=? AND (
                reconciliation_status IN ('CANDIDATE_NOT_IDENTITY','UNRESOLVED')
                OR extraction_status='UNRESOLVED'
            )
            """,
            (job_id,),
        ).fetchone()["n"]
        self._update_job(job_conn, job_id, review_count=int(review_count), progress=0.97)
        self._event(
            job_conn,
            job_id,
            "reconcile",
            "PROVISIONAL",
            "candidate sets generated; no identity promotion performed",
        )
        job_conn.commit()

    def commit_candidate_links(self, job_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist reviewed screenshot manifestations as candidate corpus links.

        This never changes flight_corpus_records.identity_status and never writes
        analytical_flight_id. A screenshot manifestation remains candidate
        evidence even after operator review unless independent binding evidence
        is added by another governed workflow.
        """
        if not self.corpus_db.is_file():
            raise ScreenshotProcessingError("canonical flight corpus database unavailable")
        if not decisions:
            raise ScreenshotProcessingError("at least one reviewed decision is required")
        job_conn = self._connect()
        corpus = sqlite3.connect(str(self.corpus_db), timeout=30.0)
        corpus.row_factory = sqlite3.Row
        try:
            corpus.execute("PRAGMA foreign_keys = ON")
            committed = 0
            for decision in decisions:
                file_id = int(decision.get("file_id"))
                corpus_record_id = int(decision.get("corpus_record_id"))
                rationale = str(decision.get("rationale") or "").strip()
                if not rationale:
                    raise ScreenshotProcessingError("review rationale is required")
                row = job_conn.execute(
                    """
                    SELECT * FROM screenshot_processing_files
                    WHERE job_id=? AND file_id=?
                    """,
                    (job_id, file_id),
                ).fetchone()
                if row is None:
                    raise ScreenshotProcessingError(f"unknown file_id {file_id}")
                candidates = json.loads(row["candidate_matches_json"]) if row["candidate_matches_json"] else []
                allowed = {int(item["corpus_record_id"]) for item in candidates if item.get("corpus_record_id") is not None}
                if corpus_record_id not in allowed:
                    raise ScreenshotProcessingError(
                        f"corpus_record_id {corpus_record_id} is outside preserved candidate set"
                    )
                target = corpus.execute(
                    "SELECT corpus_record_id FROM flight_corpus_records WHERE corpus_record_id=?",
                    (corpus_record_id,),
                ).fetchone()
                if target is None:
                    raise ScreenshotProcessingError(f"corpus record {corpus_record_id} no longer exists")
                raw_manifest = {
                    "schema_version": "skywatcher.screenshot_mfl_link.v1",
                    "job_id": job_id,
                    "file_id": file_id,
                    "payload_sha256": row["payload_sha256"],
                    "source_locator": row["source_locator"],
                    "relationship": "CANDIDATE_NOT_IDENTITY",
                    "review_rationale": rationale,
                    "reviewed_at": _utc_now(),
                }
                duplicate = corpus.execute(
                    """
                    SELECT manifestation_id FROM flight_source_manifestations
                    WHERE corpus_record_id=? AND source_kind='screenshot'
                      AND source_sha256=?
                    """,
                    (corpus_record_id, row["payload_sha256"]),
                ).fetchone()
                if duplicate is None:
                    corpus.execute(
                        """
                        INSERT INTO flight_source_manifestations
                            (corpus_record_id, source_kind, source_folder_raw,
                             source_filename_raw, source_sha256, source_mtime_raw,
                             binding_status, raw_manifest_json, created_at)
                        VALUES (?, 'screenshot', ?, ?, ?, NULL, 'candidate', ?, ?)
                        """,
                        (
                            corpus_record_id,
                            f"screenshot-processing:{job_id}",
                            row["source_locator"],
                            row["payload_sha256"],
                            _canonical_json(raw_manifest),
                            _utc_now(),
                        ),
                    )
                job_conn.execute(
                    """
                    UPDATE screenshot_processing_files
                    SET committed_corpus_record_id=?,
                        reconciliation_status='CANDIDATE_NOT_IDENTITY'
                    WHERE file_id=?
                    """,
                    (corpus_record_id, file_id),
                )
                committed += 1
            corpus.commit()
            job_conn.commit()
            self._event(
                job_conn,
                job_id,
                "commit",
                "PASS",
                f"{committed} reviewed screenshot manifestation link(s) persisted as candidate evidence",
            )
            job_conn.commit()
            return {"job_id": job_id, "committed": committed, "identity_promotions": 0}
        except Exception:
            corpus.rollback()
            job_conn.rollback()
            raise
        finally:
            corpus.close()
            job_conn.close()


_DEFAULT_STORE: ScreenshotJobStore | None = None


def get_default_store() -> ScreenshotJobStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = ScreenshotJobStore()
    return _DEFAULT_STORE


__all__ = [
    "IMAGE_EXTENSIONS",
    "CONTAINER_EXTENSIONS",
    "ScreenshotProcessingError",
    "ScreenshotJobStore",
    "get_default_store",
]
