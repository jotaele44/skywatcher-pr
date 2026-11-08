"""Moderation queue for community Sky Camera suggestions and contributed video.

Everything a member of the public submits lands here as ``pending`` and is never
listed or served until a reviewer approves it. A reviewer can later mark an approved
entry ``removed`` (takedown), which hides it and deletes any uploaded file.

Storage lives under the runtime root (``SKYWATCHER_SKY_CAMERAS_ROOT``, default
``data/sky_cameras``, gitignored): ``submissions.sqlite`` plus ``uploads/``.
Contact details are stored for the reviewer only and never appear in public payloads.
No IP address is stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from .catalog import Camera
from .validation import (
    LICENSES,
    SubmissionError,
    VideoType,
    parse_embed,
    sniff_video,
    validate_categories,
    validate_https_url,
)

KINDS = ("camera_link", "video_link", "video_upload")
STATUSES = ("pending", "approved", "rejected", "removed")
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    categories TEXT NOT NULL,
    municipality TEXT,
    lat REAL,
    lon REAL,
    description TEXT,
    contributor TEXT,
    contact TEXT,
    license TEXT NOT NULL,
    attest_rights INTEGER NOT NULL,
    attest_consent INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    reviewed_at TEXT,
    file_name TEXT,
    file_sha256 TEXT,
    file_size INTEGER,
    media_type TEXT
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: str | None, field: str, limit: int, required: bool = False) -> str | None:
    text = " ".join((value or "").split())
    if required and not text:
        raise SubmissionError(f"{field} is required")
    if len(text) > limit:
        raise SubmissionError(f"{field} is longer than {limit} characters")
    return text or None


@dataclass(frozen=True)
class SubmissionInput:
    kind: str
    title: str
    categories: list[str]
    license: str
    attest_rights: bool
    attest_consent: bool
    url: str | None = None
    municipality: str | None = None
    lat: float | None = None
    lon: float | None = None
    description: str | None = None
    contributor: str | None = None
    contact: str | None = None


class SubmissionStore:
    def __init__(self, root: Path, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES):
        self.root = Path(root)
        self.uploads = self.root / "uploads"
        self.max_upload_bytes = max_upload_bytes

    # -- storage -----------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.root / "submissions.sqlite"

    @contextmanager
    def _connect(self, create: bool = True) -> Iterator[sqlite3.Connection | None]:
        if not create and not self.db_path.is_file():
            yield None
            return
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- validation --------------------------------------------------------------
    def validate(self, data: SubmissionInput, municipios: tuple[str, ...]) -> dict[str, Any]:
        if data.kind not in KINDS:
            raise SubmissionError(f"kind must be one of {', '.join(KINDS)}")
        if not data.attest_rights:
            raise SubmissionError(
                "confirm the camera is publicly available, or that you own the video or have the right to share it"
            )
        if not data.attest_consent:
            raise SubmissionError(
                "confirm the footage does not show identifiable people without their consent or private property interiors"
            )
        if data.license not in LICENSES:
            raise SubmissionError(f"license must be one of {', '.join(LICENSES)}")
        url = None
        if data.kind == "video_upload":
            if data.url:
                raise SubmissionError("send either a file or a URL, not both")
        else:
            url = validate_https_url(data.url or "")
        municipality = _clean_text(data.municipality, "municipality", 60)
        if municipality and municipality not in municipios:
            raise SubmissionError("municipality must be one of Puerto Rico's 78 municipalities")
        lat, lon = data.lat, data.lon
        if (lat is None) != (lon is None):
            raise SubmissionError("give both latitude and longitude, or neither")
        if lat is not None and lon is not None and not (17.8 <= lat <= 18.6 and -67.95 <= lon <= -65.2):
            raise SubmissionError("coordinates must be in Puerto Rico")
        return {
            "kind": data.kind,
            "title": _clean_text(data.title, "title", 160, required=True),
            "url": url,
            "categories": validate_categories(data.categories),
            "municipality": municipality,
            "lat": data.lat,
            "lon": data.lon,
            "description": _clean_text(data.description, "description", 1000),
            "contributor": _clean_text(data.contributor, "contributor", 80),
            "contact": _clean_text(data.contact, "contact", 160),
            "license": data.license,
        }

    # -- writes ------------------------------------------------------------------
    def _store_upload(self, submission_id: str, stream: BinaryIO) -> tuple[str, str, int, VideoType]:
        self.uploads.mkdir(parents=True, exist_ok=True)
        incoming = self.uploads / f".incoming-{submission_id}"
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            with incoming.open("wb") as out:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        limit_mb = self.max_upload_bytes // (1024 * 1024)
                        raise SubmissionError(f"file is larger than the {limit_mb} MB limit")
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise SubmissionError("file is empty")
            video = sniff_video(head)
            if video is None:
                raise SubmissionError("file must be an MP4, MOV or WebM video")
            final_name = f"{submission_id}.{video.extension}"
            os.replace(incoming, self.uploads / final_name)
        finally:
            incoming.unlink(missing_ok=True)
        return final_name, digest.hexdigest(), size, video

    def create(
        self,
        data: SubmissionInput,
        municipios: tuple[str, ...],
        upload: BinaryIO | None = None,
    ) -> dict[str, Any]:
        """Validate and queue a submission as ``pending``. Raises SubmissionError."""
        if data.kind == "video_upload" and upload is None:
            raise SubmissionError("choose a video file to upload")
        if data.kind != "video_upload" and upload is not None:
            raise SubmissionError("files can only be sent with the 'share your video' option")
        fields = self.validate(data, municipios)
        submission_id = uuid.uuid4().hex
        file_name = sha = media_type = None
        size = None
        if upload is not None:
            file_name, sha, size, video = self._store_upload(submission_id, upload)
            media_type = video.media_type
        try:
            with self._connect() as conn:
                assert conn is not None
                conn.execute(
                    """INSERT INTO submissions (id, created_at, kind, title, url, categories,
                    municipality, lat, lon, description, contributor, contact, license,
                    attest_rights, attest_consent, status, file_name, file_sha256, file_size,
                    media_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)""",
                    (
                        submission_id, _now(), fields["kind"], fields["title"], fields["url"],
                        json.dumps(fields["categories"]), fields["municipality"], fields["lat"],
                        fields["lon"], fields["description"], fields["contributor"],
                        fields["contact"], fields["license"], 1, 1, file_name, sha, size, media_type,
                    ),
                )
        except Exception:
            if file_name:
                (self.uploads / file_name).unlink(missing_ok=True)
            raise
        return self.get(submission_id) or {}

    def decide(self, submission_id: str, decision: str, note: str | None = None) -> dict[str, Any] | None:
        """Approve, reject or remove (take down) a submission. Returns the updated row."""
        if decision not in ("approved", "rejected", "removed"):
            raise SubmissionError("decision must be approved, rejected or removed")
        note = _clean_text(note, "note", 500)
        with self._connect() as conn:
            assert conn is not None
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            if row is None:
                return None
            if decision == "removed" and row["status"] != "approved":
                raise SubmissionError("only an approved submission can be taken down")
            conn.execute(
                "UPDATE submissions SET status = ?, review_note = ?, reviewed_at = ? WHERE id = ?",
                (decision, note, _now(), submission_id),
            )
        if decision in ("rejected", "removed") and row["file_name"]:
            (self.uploads / row["file_name"]).unlink(missing_ok=True)
        return self.get(submission_id)

    # -- reads -------------------------------------------------------------------
    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["categories"] = json.loads(out["categories"])
        out["attest_rights"] = bool(out["attest_rights"])
        out["attest_consent"] = bool(out["attest_consent"])
        return out

    def get(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect(create=False) as conn:
            if conn is None:
                return None
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect(create=False) as conn:
            if conn is None:
                return []
            if status:
                rows = conn.execute(
                    "SELECT * FROM submissions WHERE status = ? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM submissions ORDER BY created_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def media_path(self, submission_id: str) -> tuple[Path, str] | None:
        """The stored file of an *approved* upload, else None."""
        row = self.get(submission_id)
        if not row or row["status"] != "approved" or not row["file_name"]:
            return None
        path = self.uploads / row["file_name"]
        return (path, row["media_type"]) if path.is_file() else None


def submission_receipt(row: dict[str, Any]) -> dict[str, Any]:
    """What the submitter sees back: no contact details, no storage paths."""
    return {
        "id": row["id"],
        "status": row["status"],
        "kind": row["kind"],
        "title": row["title"],
        "created_at": row["created_at"],
        "message": "Thanks! Your submission is in the review queue and will appear once a reviewer approves it.",
    }


def community_camera(row: dict[str, Any], media_url: str | None = None) -> Camera:
    """Turn an approved submission into a public catalog entry."""
    embed = None
    if row["kind"] == "video_link" and row["url"]:
        # The contributor attested they own this video, so their own embed is allowed.
        embed = parse_embed(row["url"])
    page_url = row["url"] or media_url or ""
    provider = "Community contribution"
    if row["kind"] == "camera_link":
        provider = "Community suggestion"
    return Camera(
        id=f"community-{row['id'][:12]}",
        name=row["title"],
        categories=tuple(row["categories"]),
        municipality=row["municipality"],
        lat=row["lat"],
        lon=row["lon"],
        provider=provider,
        page_url=page_url,
        embed=embed,
        terms_note=(
            "Contributed under CC BY 4.0." if row["license"] == "cc-by-4.0"
            else "Shown here with the contributor's permission; all other rights reserved."
        ),
        source_url=page_url,
        verified_at=(row["reviewed_at"] or row["created_at"])[:10],
        last_known_status="online" if row["kind"] != "camera_link" else "unknown",
        added_by="community",
        contributor=row["contributor"],
        license=row["license"],
        media_url=media_url,
        description=row["description"],
    )
