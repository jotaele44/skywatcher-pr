"""Durable, fail-closed runtime intake for Skywatcher screenshot batches.

This is a staging controller, not an alternative flight log or OCR database.
Original bytes and every source manifestation stay on operator-local storage.
No screenshot observation becomes a canonical flight through this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import stat
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
ALLOWED_EXTS = IMAGE_EXTS | {".zip", ".pdf"}
TERMINAL = {"NEEDS_REVIEW", "EXTRACTED_EMPTY", "REVIEWED", "FAILED", "BLOCKED"}
MAX_SOURCES = 32
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_BATCH_BYTES = 40 * 1024 * 1024
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_MEMBERS = 300
MAX_PDF_PAGES = 60


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_settings(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    allowed = {"ocr_mode": {"local"}, "vision_mode": {"off"}, "duplicate_mode": {"exact"}}
    if set(value) - set(allowed):
        raise ValueError("unsupported settings: " + ", ".join(sorted(set(value) - set(allowed))))
    settings = {k: value.get(k, next(iter(v))) for k, v in allowed.items()}
    for key, options in allowed.items():
        if settings[key] not in options:
            raise ValueError(f"{key} is not implemented in this release")
    return settings


def _clean_label(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 240 or "\x00" in name:
        raise ValueError("invalid source filename")
    # Original label is recorded; no user-controlled path is used for writes.
    return name


def _expand_payload(data: bytes, label: str, *, parent: str = "", depth: int = 0):
    """Yield (name, member, page, bytes, error); blocked items are explicit."""
    extension = Path(label).suffix.lower()
    if extension in IMAGE_EXTS:
        if len(data) > MAX_SOURCE_BYTES:
            yield label, parent, None, b"", "image exceeds size limit"
        else:
            yield label, parent, None, data, None
        return
    if extension == ".zip":
        if depth > 0:
            yield label, parent, None, b"", "nested archives are not accepted"
            return
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            with archive:
                members = [info for info in archive.infolist() if not info.is_dir()]
                if len(members) > MAX_MEMBERS:
                    yield label, parent, None, b"", "archive member limit exceeded"
                    return
                total = 0
                for idx, info in enumerate(members):
                    member = f"{idx}:{info.filename}"
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode) or info.flag_bits & 1:
                        yield info.filename, member, None, b"", "symlink or encrypted archive member"
                        continue
                    if info.file_size > MAX_SOURCE_BYTES:
                        yield info.filename, member, None, b"", "member exceeds size limit"
                        continue
                    total += info.file_size
                    if total > MAX_EXPANDED_BYTES:
                        yield info.filename, member, None, b"", "expanded archive budget exceeded"
                        # Stop safely. The full member denominator remains frozen below.
                        for j, remaining in enumerate(members[idx + 1:], start=idx + 1):
                            yield remaining.filename, f"{j}:{remaining.filename}", None, b"", "archive budget exhausted"
                        return
                    if info.compress_size and info.file_size / info.compress_size > 100:
                        yield info.filename, member, None, b"", "archive compression ratio exceeds limit"
                        continue
                    try:
                        payload = archive.read(info)
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        yield info.filename, member, None, b"", f"unreadable member: {type(exc).__name__}"
                        continue
                    yield from _expand_payload(payload, info.filename, parent=member, depth=depth + 1)
        except (OSError, zipfile.BadZipFile):
            yield label, parent, None, b"", "invalid ZIP archive"
        return
    if extension == ".pdf":
        try:
            import fitz  # PyMuPDF; optional, fail closed when absent
        except ImportError:
            yield label, parent, None, b"", "PDF renderer unavailable (install PyMuPDF)"
            return
        try:
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.is_encrypted:
                    yield label, parent, None, b"", "encrypted PDF"
                    return
                if pdf.page_count > MAX_PDF_PAGES:
                    yield label, parent, None, b"", f"PDF exceeds {MAX_PDF_PAGES} page limit"
                    return
                for page_no in range(pdf.page_count):
                    try:
                        page = pdf.load_page(page_no)
                        if page.rect.width * page.rect.height > 20_000_000:
                            raise ValueError("page exceeds image pixel limit")
                        rendered = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
                        image_bytes = rendered.tobytes("png")
                        if len(image_bytes) > MAX_SOURCE_BYTES:
                            raise ValueError("rendered page exceeds byte limit")
                        yield f"{label}#page={page_no + 1}.png", parent, page_no + 1, image_bytes, None
                    except (ValueError, RuntimeError, MemoryError) as exc:
                        yield label, parent, page_no + 1, b"", f"PDF page render failed: {type(exc).__name__}"
        except (ValueError, RuntimeError, OSError) as exc:
            yield label, parent, None, b"", f"PDF parsing failed: {type(exc).__name__}"
        return
    yield label, parent, None, b"", "unsupported source type"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 status TEXT NOT NULL, settings_json TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS sources (
 source_id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
 ordinal INTEGER NOT NULL, original_name TEXT NOT NULL, sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, saved_path TEXT NOT NULL,
 UNIQUE(job_id, ordinal));
CREATE TABLE IF NOT EXISTS items (
 item_id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
 source_id INTEGER NOT NULL REFERENCES sources(source_id),
 ordinal INTEGER NOT NULL, filename_raw TEXT NOT NULL, member_path TEXT,
 page_number INTEGER, sha256 TEXT, size_bytes INTEGER,
 saved_path TEXT, status TEXT NOT NULL, error TEXT,
 screenshot_id INTEGER, was_reused INTEGER NOT NULL DEFAULT 0,
 fields_json TEXT, contradictions_json TEXT, review_note TEXT,
 UNIQUE(job_id, source_id, ordinal));
CREATE TABLE IF NOT EXISTS candidate_links (
 item_id INTEGER NOT NULL REFERENCES items(item_id), corpus_record_id INTEGER NOT NULL,
 snapshot_id INTEGER NOT NULL, corpus_uid TEXT NOT NULL, callsign_raw TEXT,
 start_time_utc TEXT, end_time_utc TEXT, association_status TEXT NOT NULL,
 PRIMARY KEY(item_id, corpus_record_id));
CREATE INDEX IF NOT EXISTS ix_items_job ON items(job_id, status);
CREATE INDEX IF NOT EXISTS ix_sources_job ON sources(job_id);
"""


class ScreenshotJobs:
    def __init__(self, root: Path, *, work_root: Path | None = None,
                 rlsm_db: Path | None = None, corpus_db: Path | None = None,
                 extractor=None):
        self.root = root.resolve()
        self.work = (work_root or self.root / "inputs" / "screenshots" / "runtime").resolve()
        self.db = self.work / "jobs.sqlite"
        self.rlsm_db = rlsm_db or self.root / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
        self.corpus_db = corpus_db or self.root / "data" / "skywatcher.db"
        self.extractor = extractor
        self._worker_lock = threading.Lock()
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute("UPDATE jobs SET status='QUEUED',updated_at=? WHERE status='RUNNING'", (now(),))
            conn.execute("UPDATE items SET status='QUEUED' WHERE status='RUNNING'")

    def create(self, sources: list[tuple[str, bytes]], settings: dict | None = None):
        options = validate_settings(settings or {})
        if not 1 <= len(sources) <= MAX_SOURCES:
            raise ValueError("source count must be between 1 and 32")
        if sum(len(data) for _, data in sources) > MAX_BATCH_BYTES:
            raise ValueError("batch exceeds 40 MiB")
        job_id = str(uuid.uuid4())
        directory = self.work / job_id
        directory.mkdir(mode=0o700)
        try:
            with self._connect() as conn:
                conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,NULL)",
                             (job_id, now(), now(), "QUEUED", json.dumps(options, sort_keys=True)))
                for source_idx, (name, data) in enumerate(sources):
                    label = _clean_label(name)
                    if not data or len(data) > MAX_SOURCE_BYTES or Path(label).suffix.lower() not in ALLOWED_EXTS:
                        raise ValueError(f"invalid or oversized source #{source_idx + 1}")
                    path = directory / f"source-{source_idx:04d}.bin"
                    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as fp:
                        fp.write(data)
                    source_id = conn.execute(
                        "INSERT INTO sources (job_id,ordinal,original_name,sha256,size_bytes,saved_path) VALUES (?,?,?,?,?,?)",
                        (job_id, source_idx, label, digest(data), len(data), str(path))
                    ).lastrowid
                    for item_idx, (item_name, member, page, payload, problem) in enumerate(_expand_payload(data, label)):
                        if item_idx >= MAX_MEMBERS + MAX_PDF_PAGES:
                            raise ValueError("expanded item count exceeds safety limit")
                        item_path = None
                        sha = None
                        if not problem:
                            item_path = directory / f"item-{source_idx:04d}-{item_idx:04d}.png"
                            # Store original format for Pillow/Tesseract using its genuine suffix.
                            item_path = item_path.with_suffix(Path(item_name).suffix.lower())
                            with os.fdopen(os.open(item_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as fp:
                                fp.write(payload)
                            sha = digest(payload)
                        conn.execute("""INSERT INTO items
                          (job_id,source_id,ordinal,filename_raw,member_path,page_number,
                           sha256,size_bytes,saved_path,status,error)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (job_id, source_id, item_idx, item_name, member or None, page,
                           sha, len(payload) if payload else None,
                           str(item_path) if item_path else None,
                           "BLOCKED" if problem else "QUEUED", problem))
            return self.detail(job_id)
        except Exception:
            # Do not leave an orphan original when a failed preflight rolls back.
            for file in directory.iterdir():
                file.unlink()
            directory.rmdir()
            raise

    def detail(self, job_id: str, *, include_items: bool = False):
        with self._connect() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                raise KeyError("job not found")
            tally = {r["status"]: r["n"] for r in conn.execute(
                "SELECT status,COUNT(*) n FROM items WHERE job_id=? GROUP BY status", (job_id,))}
            total = sum(tally.values())
            complete = sum(tally.get(key, 0) for key in TERMINAL)
            response = {
                "job_id": job_id, "status": job["status"], "settings": json.loads(job["settings_json"]),
                "created_at": job["created_at"], "updated_at": job["updated_at"],
                "error": job["error"], "total": total, "complete": complete,
                "progress": (complete / total if total else 0.0), "counts": tally,
            }
            if include_items:
                response["sources"] = [dict(r) for r in conn.execute(
                    "SELECT ordinal,original_name,sha256,size_bytes FROM sources WHERE job_id=? ORDER BY ordinal", (job_id,))]
                items = [dict(r) for r in conn.execute(
                    """SELECT item_id,ordinal,filename_raw,member_path,page_number,sha256,size_bytes,
                       status,error,screenshot_id,was_reused,fields_json,contradictions_json,review_note
                       FROM items WHERE job_id=? ORDER BY source_id,ordinal""", (job_id,))]
                for item in items:
                    item["fields"] = json.loads(item.pop("fields_json") or "{}")
                    item["contradictions"] = json.loads(item.pop("contradictions_json") or "[]")
                    item["candidates"] = [dict(r) for r in conn.execute(
                        """SELECT corpus_record_id,snapshot_id,corpus_uid,callsign_raw,
                           start_time_utc,end_time_utc,association_status
                           FROM candidate_links WHERE item_id=? ORDER BY corpus_record_id""",
                        (item["item_id"],))]
                response["items"] = items
            return response

    def list_jobs(self):
        with self._connect() as conn:
            ids = [r["job_id"] for r in conn.execute(
                "SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 30")]
        return [self.detail(job_id) for job_id in ids]

    def control(self, job_id: str, action: str):
        if action not in {"pause", "resume", "cancel"}:
            raise ValueError("unknown action")
        states = {"pause": ({"QUEUED", "RUNNING"}, "PAUSED"),
                  "resume": ({"PAUSED", "QUEUED"}, "QUEUED"),
                  "cancel": ({"QUEUED", "RUNNING", "PAUSED"}, "CANCELLED")}
        allowed, target = states[action]
        with self._connect() as conn:
            current = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if current is None:
                raise KeyError("job not found")
            if current["status"] not in allowed:
                raise ValueError(f"cannot {action} job in {current['status']}")
            conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE job_id=?", (target, now(), job_id))
            if target == "CANCELLED":
                conn.execute("UPDATE items SET status='BLOCKED',error='cancelled before processing' "
                             "WHERE job_id=? AND status='QUEUED'", (job_id,))
        if action == "resume":
            self.kick()
        return self.detail(job_id)

    def review(self, job_id: str, item_id: int, note: str):
        if not 3 <= len(note.strip()) <= 2000:
            raise ValueError("review note must contain 3–2000 characters")
        with self._connect() as conn:
            result = conn.execute("UPDATE items SET status='REVIEWED',review_note=? "
                                  "WHERE item_id=? AND job_id=? AND status='NEEDS_REVIEW'",
                                  (note, item_id, job_id))
            if result.rowcount != 1:
                raise ValueError("only staged review candidates may be marked reviewed")
        return self.detail(job_id, include_items=True)

    def kick(self):
        thread = threading.Thread(target=self._drain, daemon=True, name="skywatcher-screenshot-intake")
        thread.start()

    def _drain(self):
        if not self._worker_lock.acquire(blocking=False):
            return
        try:
            while True:
                with self._connect() as conn:
                    job = conn.execute("SELECT job_id FROM jobs WHERE status='QUEUED' ORDER BY created_at LIMIT 1").fetchone()
                    if job is None:
                        return
                    job_id = job["job_id"]
                    conn.execute("UPDATE jobs SET status='RUNNING',updated_at=? WHERE job_id=?", (now(), job_id))
                self._run(job_id)
        finally:
            self._worker_lock.release()

    def _run(self, job_id):
        if self.extractor is None:
            from skywatcher.fr24.screenshot_rlsm_adapter import extract_into_rlsm
            engine = extract_into_rlsm
        else:
            engine = self.extractor
        while True:
            with self._connect() as conn:
                state = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()["status"]
                if state != "RUNNING":
                    return
                item = conn.execute("SELECT * FROM items WHERE job_id=? AND status='QUEUED' "
                                    "ORDER BY source_id,ordinal LIMIT 1", (job_id,)).fetchone()
                if item is None:
                    issues = conn.execute("SELECT COUNT(*) FROM items WHERE job_id=? "
                                          "AND status IN ('BLOCKED','FAILED')", (job_id,)).fetchone()[0]
                    reviews = conn.execute("SELECT COUNT(*) FROM items WHERE job_id=? "
                                           "AND status='NEEDS_REVIEW'", (job_id,)).fetchone()[0]
                    completed_state = "COMPLETE_WITH_BLOCKERS" if issues else ("READY_FOR_REVIEW" if reviews else "COMPLETE")
                    conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE job_id=?",
                                 (completed_state, now(), job_id))
                    return
                conn.execute("UPDATE items SET status='RUNNING' WHERE item_id=?", (item["item_id"],))
            try:
                result = engine(Path(item["saved_path"]), item["sha256"],
                                self.root, self.rlsm_db, self.corpus_db,
                                filename_raw=item["filename_raw"])
                if not isinstance(result, dict) or result.get("status") not in {"NEEDS_REVIEW", "EXTRACTED_EMPTY", "BLOCKED"}:
                    raise ValueError("extractor returned an invalid stage receipt")
                status = result["status"]
                fields = json.dumps(result.get("fields", {}), ensure_ascii=False, sort_keys=True)
                contradictions = json.dumps(result.get("contradictions", []), ensure_ascii=False)
                candidates = result.get("candidates", [])
                with self._connect() as conn:
                    conn.execute("""UPDATE items SET status=?,screenshot_id=?,was_reused=?,
                        fields_json=?,contradictions_json=?,error=? WHERE item_id=?""",
                        (status, result.get("screenshot_id"), int(bool(result.get("was_reused"))),
                         fields, contradictions, result.get("error"), item["item_id"]))
                    for candidate in candidates:
                        conn.execute("""INSERT OR IGNORE INTO candidate_links
                            (item_id,corpus_record_id,snapshot_id,corpus_uid,callsign_raw,
                             start_time_utc,end_time_utc,association_status)
                            VALUES (?,?,?,?,?,?,?,'CANDIDATE_NOT_IDENTITY')""",
                            (item["item_id"], candidate["corpus_record_id"], candidate["snapshot_id"],
                             candidate["corpus_uid"], candidate.get("callsign_raw"),
                             candidate.get("start_time_utc"), candidate.get("end_time_utc")))
            except Exception as exc:
                with self._connect() as conn:
                    conn.execute("UPDATE items SET status='FAILED',error=? WHERE item_id=?",
                                 (f"{type(exc).__name__}: {exc}"[:500], item["item_id"]))
            with self._connect() as conn:
                conn.execute("UPDATE jobs SET updated_at=? WHERE job_id=?", (now(), job_id))
