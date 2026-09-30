"""Authenticated, bounded screenshot-intake API.

Every endpoint requires an explicitly configured bearer token, including reads.
Unlike legacy diagnostic writes, this router never permits anonymous LAN writes.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from skywatcher.fr24.screenshot_jobs import (
    MAX_BATCH_BYTES,
    MAX_SOURCES,
    ScreenshotJobs,
)

ROOT = Path(__file__).resolve().parents[2]
MAX_REQUEST_BYTES = 48 * 1024 * 1024


def require_screenshot_access(request: Request) -> None:
    token = os.environ.get("SKYWATCHER_SCREENSHOT_TOKEN") or os.environ.get("PRII_WRITE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="configure SKYWATCHER_SCREENSHOT_TOKEN before using screenshot intake")
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(presented, token):
        raise HTTPException(status_code=401, detail="invalid or missing screenshot-intake token")


router = APIRouter(
    prefix="/api/screenshot-runs",
    tags=["screenshot-intake"],
    dependencies=[Depends(require_screenshot_access)],
)


@lru_cache(maxsize=1)
def store() -> ScreenshotJobs:
    # Custom work-root must remain under the repository to retain RLSM path invariants.
    root = ROOT.resolve()
    configured = os.environ.get("SKYWATCHER_SCREENSHOT_WORK_ROOT")
    work_root = Path(configured).resolve() if configured else root / "inputs" / "screenshots" / "runtime"
    try:
        work_root.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("screenshot work root must reside beneath the Skywatcher repository") from exc
    jobs = ScreenshotJobs(
        root,
        work_root=work_root,
        corpus_db=Path(os.environ.get("SKYWATCHER_DB", str(root / "data" / "skywatcher.db"))),
    )
    jobs.kick()  # Recover interrupted jobs on application restart.
    return jobs


async def _bounded_json(request: Request) -> dict:
    size = request.headers.get("content-length")
    if size:
        try:
            if int(size) > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="request exceeds 48 MiB")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="request exceeds 48 MiB")
    try:
        value = json.loads(buffer)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="malformed JSON upload") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="upload must be an object")
    return value


@router.post("")
async def create_run(request: Request):
    body = await _bounded_json(request)
    raw = body.get("files")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SOURCES:
        raise HTTPException(status_code=400, detail="supply 1–32 source files")
    decoded = []
    total = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise HTTPException(status_code=400, detail=f"invalid file descriptor #{index + 1}")
        encoded = item.get("data_base64")
        if not isinstance(encoded, str) or len(encoded) > 46 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="source file exceeds encoded size limit")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail=f"invalid base64 in file #{index + 1}") from exc
        total += len(payload)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(status_code=413, detail="decoded batch exceeds 40 MiB")
        decoded.append((item["name"], payload))
    try:
        result = store().create(decoded, body.get("settings", {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store().kick()
    return result


@router.get("")
def list_runs():
    return {"jobs": store().list_jobs()}


@router.get("/{job_id}")
def get_run(job_id: str):
    try:
        return store().detail(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.get("/{job_id}/results")
def get_results(job_id: str):
    try:
        return store().detail(job_id, include_items=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.post("/{job_id}/control")
async def control_run(job_id: str, request: Request):
    body = await _bounded_json(request)
    try:
        return store().control(job_id, body.get("action", ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/review")
async def review_item(job_id: str, request: Request):
    body = await _bounded_json(request)
    try:
        item_id = int(body.get("item_id"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="valid item_id required") from exc
    try:
        return store().review(job_id, item_id, body.get("note", ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
