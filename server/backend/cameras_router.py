"""Sky Cameras API: the curated public-camera catalog and the moderated contribution queue.

Public, read-only:
  GET  /api/sky-cameras                 curated catalog + approved community entries
  GET  /api/sky-cameras/coverage        cameras per category / municipality, with gaps
  GET  /api/sky-cameras/media/{id}      an approved uploaded clip (404 otherwise)

Public intake (writes only to the quarantine queue, never publishes):
  POST /api/sky-cameras/submissions     multipart: a link, or a video file

Reviewer (behind the same write guard as every other mutating route):
  GET  /api/sky-cameras/submissions
  POST /api/sky-cameras/submissions/{id}/decision
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from skywatcher.core.cameras import (
    CATEGORIES,
    SubmissionError,
    SubmissionInput,
    SubmissionStore,
    community_camera,
    coverage_summary,
    filter_cameras,
    load_catalog,
    load_municipios,
    load_status,
    submission_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(tags=["sky-cameras"])

_RATE_WINDOW_S = 3600.0
_rate_lock = threading.Lock()
_rate_hits: dict[str, deque[float]] = {}


def _catalog_dir() -> Path:
    configured = os.environ.get("SKYWATCHER_SKY_CAMERAS_CATALOG_DIR")
    return Path(configured) if configured else ROOT / "data" / "reference" / "sky_cameras"


def _runtime_root() -> Path:
    configured = os.environ.get("SKYWATCHER_SKY_CAMERAS_ROOT")
    return Path(configured) if configured else ROOT / "data" / "sky_cameras"


def _max_upload_bytes() -> int:
    try:
        megabytes = int(os.environ.get("SKYWATCHER_SKY_CAMERAS_MAX_UPLOAD_MB", "100"))
    except ValueError:
        megabytes = 100
    return max(1, megabytes) * 1024 * 1024


def _rate_limit() -> int:
    try:
        return int(os.environ.get("SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR", "20"))
    except ValueError:
        return 20


def _store() -> SubmissionStore:
    return SubmissionStore(_runtime_root(), max_upload_bytes=_max_upload_bytes())


def _municipios() -> tuple[str, ...]:
    return load_municipios(ROOT / "data" / "geo" / "pr_municipios_boundaries.json")


def require_reviewer(request: Request) -> None:
    """Reviewer routes use the backend's single write guard (imported lazily: main imports us)."""
    from server.backend import main

    main.require_write_access(request)


_REVIEWER_GUARD = [Depends(require_reviewer)]


def _all_cameras() -> list:
    try:
        curated = list(load_catalog(_catalog_dir()))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail={"state": "CATALOG_MISSING"}) from exc
    community = []
    for row in _store().list(status="approved"):
        media_url = f"/api/sky-cameras/media/{row['id']}" if row["file_name"] else None
        community.append(community_camera(row, media_url=media_url))
    return curated + community


@router.get("/api/sky-cameras")
def sky_cameras(
    category: Literal["sky", "beach", "coast", "mountain", "river", "lake", "lagoon", "city"] | None = None,
    municipality: str | None = Query(default=None, max_length=60),
    q: str | None = Query(default=None, max_length=120),
) -> dict[str, Any]:
    statuses = load_status(_runtime_root())
    cameras = filter_cameras(_all_cameras(), category=category, municipality=municipality, q=q)
    return {
        "categories": list(CATEGORIES),
        "municipios": list(_municipios()),
        "count": len(cameras),
        "cameras": [camera.to_payload(statuses.get(camera.id)) for camera in cameras],
    }


@router.get("/api/sky-cameras/coverage")
def sky_cameras_coverage() -> dict[str, Any]:
    return coverage_summary(_all_cameras(), _municipios(), load_status(_runtime_root()))


@router.get("/api/sky-cameras/media/{submission_id}")
def sky_cameras_media(submission_id: str) -> FileResponse:
    if not submission_id.isalnum() or len(submission_id) != 32:
        raise HTTPException(status_code=404, detail="Not found")
    found = _store().media_path(submission_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    path, media_type = found
    return FileResponse(path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})


def _check_rate(request: Request) -> None:
    limit = _rate_limit()
    if limit <= 0:
        return
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits.setdefault(key, deque())
        while hits and now - hits[0] > _RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(status_code=429, detail="Too many submissions; try again later")
        hits.append(now)


def _flag(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _number(value: Any, field: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise SubmissionError(f"{field} must be a number") from exc


@router.post("/api/sky-cameras/submissions", status_code=201)
async def sky_cameras_submit(request: Request) -> dict[str, Any]:
    """Queue a camera suggestion or a contributed video for review. Never publishes."""
    limit = _max_upload_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Upload is larger than the {limit // (1024 * 1024)} MB limit")
    _check_rate(request)
    try:
        form = await request.form(max_files=1, max_fields=20)
    except Exception as exc:  # malformed multipart bodies
        raise HTTPException(status_code=400, detail="Send the form as multipart/form-data") from exc
    upload = form.get("file")
    try:
        if upload is not None and not isinstance(upload, UploadFile):
            raise SubmissionError("file must be a file upload")
        data = SubmissionInput(
            kind=str(form.get("kind") or ""),
            title=str(form.get("title") or ""),
            url=str(form.get("url") or "") or None,
            categories=[str(value) for value in form.getlist("categories")],
            municipality=str(form.get("municipality") or "") or None,
            lat=_number(form.get("lat"), "latitude"),
            lon=_number(form.get("lon"), "longitude"),
            description=str(form.get("description") or "") or None,
            contributor=str(form.get("contributor") or "") or None,
            contact=str(form.get("contact") or "") or None,
            license=str(form.get("license") or ""),
            attest_rights=_flag(form.get("attest_rights")),
            attest_consent=_flag(form.get("attest_consent")),
        )
        row = _store().create(data, _municipios(), upload=upload.file if upload else None)
    except SubmissionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await form.close()
    return submission_receipt(row)


@router.get("/api/sky-cameras/submissions", dependencies=_REVIEWER_GUARD)
def sky_cameras_submissions(
    status: Literal["pending", "approved", "rejected", "removed"] | None = "pending",
) -> dict[str, Any]:
    rows = _store().list(status=status)
    for row in rows:
        row["media_url"] = f"/api/sky-cameras/submissions/{row['id']}/media" if row["file_name"] else None
    return {"status": status, "count": len(rows), "submissions": rows}


@router.get("/api/sky-cameras/submissions/{submission_id}/media", dependencies=_REVIEWER_GUARD)
def sky_cameras_submission_media(submission_id: str) -> FileResponse:
    """Reviewers preview a pending upload before deciding."""
    row = _store().get(submission_id)
    if not row or not row["file_name"] or row["status"] in ("rejected", "removed"):
        raise HTTPException(status_code=404, detail="Not found")
    path = _store().uploads / row["file_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type=row["media_type"], headers={"X-Content-Type-Options": "nosniff"})


class Decision(BaseModel):
    decision: Literal["approved", "rejected", "removed"]
    note: str | None = Field(default=None, max_length=500)


@router.post("/api/sky-cameras/submissions/{submission_id}/decision", dependencies=_REVIEWER_GUARD)
def sky_cameras_decide(submission_id: str, body: Decision) -> dict[str, Any]:
    try:
        row = _store().decide(submission_id, body.decision, body.note)
    except SubmissionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row
