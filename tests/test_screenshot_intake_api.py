"""Authenticated HTTP regression for the new isolated screenshot router."""
from __future__ import annotations

import base64
import time

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def _fake_extractor(path, sha, root, rlsm_db, corpus_db, *, filename_raw=None):
    return {
        "status": "NEEDS_REVIEW",
        "screenshot_id": 44,
        "fields": {"registration": {"value": "N123AB", "certification": "CANDIDATE_NOT_IDENTITY"}},
        "contradictions": [],
        "candidates": [],
    }


def test_http_upload_requires_token_and_reports_real_terminal_progress(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    import server.backend.screenshot_router as api
    from skywatcher.fr24.screenshot_jobs import ScreenshotJobs

    jobs = ScreenshotJobs(tmp_path, extractor=_fake_extractor)
    monkeypatch.setattr(api, "store", lambda: jobs)
    monkeypatch.setenv("SKYWATCHER_SCREENSHOT_TOKEN", "fixture-token")
    app = FastAPI()
    app.include_router(api.router)
    payload = {
        "files": [{
            "name": "IMG_0001.png",
            "data_base64": base64.b64encode(b"bounded-fixture").decode("ascii"),
        }],
        "settings": {"ocr_mode": "local", "vision_mode": "off", "duplicate_mode": "exact"},
    }
    with TestClient(app) as client:
        assert client.get("/api/screenshot-runs").status_code == 401
        denied = client.post(
            "/api/screenshot-runs",
            headers={"Authorization": "Bearer wrong"},
            json=payload,
        )
        assert denied.status_code == 401
        created = client.post(
            "/api/screenshot-runs",
            headers={"Authorization": "Bearer fixture-token"},
            json=payload,
        )
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        detail = None
        for _ in range(100):
            detail = client.get(
                "/api/screenshot-runs/" + job_id,
                headers={"Authorization": "Bearer fixture-token"},
            )
            if detail.json()["status"] in {"READY_FOR_REVIEW", "COMPLETE_WITH_BLOCKERS", "COMPLETE"}:
                break
            time.sleep(0.01)
        assert detail is not None
        assert detail.status_code == 200
        assert detail.json()["status"] == "READY_FOR_REVIEW"
        assert detail.json()["complete"] == detail.json()["total"] == 1
        results = client.get(
            "/api/screenshot-runs/" + job_id + "/results",
            headers={"Authorization": "Bearer fixture-token"},
        )
        assert results.status_code == 200
        item = results.json()["items"][0]
        assert item["filename_raw"] == "IMG_0001.png"
        assert item["fields"]["registration"]["certification"] == "CANDIDATE_NOT_IDENTITY"


def test_http_rejects_unimplemented_external_vision(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    import server.backend.screenshot_router as api
    from skywatcher.fr24.screenshot_jobs import ScreenshotJobs

    monkeypatch.setattr(api, "store", lambda: ScreenshotJobs(tmp_path, extractor=_fake_extractor))
    monkeypatch.setenv("SKYWATCHER_SCREENSHOT_TOKEN", "fixture-token")
    app = FastAPI()
    app.include_router(api.router)
    payload = {
        "files": [{
            "name": "IMG_0001.png",
            "data_base64": base64.b64encode(b"fixture").decode("ascii"),
        }],
        "settings": {"vision_mode": "comprehensive"},
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/screenshot-runs",
            headers={"Authorization": "Bearer fixture-token"},
            json=payload,
        )
    assert response.status_code == 400
    assert "not implemented" in response.json()["detail"]
