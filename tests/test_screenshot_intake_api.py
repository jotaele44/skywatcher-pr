"""Authenticated HTTP regression for the new isolated screenshot router."""
from __future__ import annotations

import base64
import time

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def _fake_extractor(path, sha, root, rlsm_db, corpus_db, *, filename_raw=None, reprocess_existing=False):
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
        image = client.get(
            "/api/screenshot-runs/" + job_id + "/items/" + str(item["item_id"]) + "/image",
            headers={"Authorization": "Bearer fixture-token"},
        )
        assert image.status_code == 200
        assert image.headers["cache-control"] == "no-store"
        assert base64.b64decode(image.json()["data_base64"]) == b"bounded-fixture"


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



def test_certification_routes_are_authenticated_and_static(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    import server.backend.screenshot_router as api

    class FakeCertification:
        def readiness(self):
            return {
                "schema_version": "fixture",
                "certification_ready_for_audit": True,
                "operator_pipeline_ready": True,
            }

        def generate_gold_template(self):
            return {
                "name": "gold_sample_300.template.jsonl",
                "sha256": "a" * 64,
                "data_base64": base64.b64encode(b"{}\n").decode("ascii"),
                "selection_manifest": {"selected_rows": 300},
            }

        def list_receipts(self, limit=20):
            return [{"run_id": "fixture-run", "certification_status": "BLOCKED"}][:limit]

        def run_audit(self, name, payload):
            assert name == "gold.jsonl"
            assert payload == b"{}\n"
            return {
                "run_id": "fixture-run",
                "certification_status": "BLOCKED",
                "canonical_mfl_mutation_authorized": False,
            }

    monkeypatch.setattr(api, "certification_service", lambda: FakeCertification())
    monkeypatch.setenv("SKYWATCHER_SCREENSHOT_TOKEN", "fixture-token")
    app = FastAPI()
    app.include_router(api.router)

    with TestClient(app) as client:
        assert client.get("/api/screenshot-runs/certification/status").status_code == 401

        headers = {"Authorization": "Bearer fixture-token"}
        status = client.get(
            "/api/screenshot-runs/certification/status",
            headers=headers,
        )
        assert status.status_code == 200
        assert status.json()["certification_ready_for_audit"] is True

        template = client.get(
            "/api/screenshot-runs/certification/template",
            headers=headers,
        )
        assert template.status_code == 200
        assert template.json()["selection_manifest"]["selected_rows"] == 300

        runs = client.get(
            "/api/screenshot-runs/certification/runs",
            headers=headers,
        )
        assert runs.status_code == 200
        assert runs.json()["runs"][0]["run_id"] == "fixture-run"

        audit = client.post(
            "/api/screenshot-runs/certification/audit",
            headers=headers,
            json={
                "name": "gold.jsonl",
                "data_base64": base64.b64encode(b"{}\n").decode("ascii"),
            },
        )
        assert audit.status_code == 200
        assert audit.json()["canonical_mfl_mutation_authorized"] is False

        invalid = client.post(
            "/api/screenshot-runs/certification/audit",
            headers=headers,
            json={"name": "gold.jsonl", "data_base64": "not-base64!"},
        )
        assert invalid.status_code == 400
