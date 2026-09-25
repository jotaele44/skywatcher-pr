from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def _backend():
    import server.backend.main as backend

    return backend


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "generated_as_of": "2026-09-25",
        "source_corpus_sha256": "abc",
        "coverage_ledger_merge_sha": "def",
        "execution_receipt": {
            "attempted_at": "2026-09-25T07:03:00Z",
            "target_count": 1,
            "discovery_requests_issued": 0,
            "playback_requests_issued": 0,
            "quota_units_spent": 0,
            "result": "BLOCKED_EXTERNAL_AUTH",
            "resumable": True,
        },
        "targets": [
            {
                "acquisition_id": "P1-N1-20260901-20260910",
                "type": "GAP",
                "identity": "N1",
                "from": "2026-09-01",
                "to": "2026-09-10",
                "recoverable_from": "2026-09-01",
                "recoverable_to": "2026-09-10",
                "lost_days": 0,
                "priority_score": 100,
                "priority_tier": "P1",
                "deadline": "2027-09-01",
                "days_left_at_freeze": 341,
                "discovery_status": "BLOCKED_EXTERNAL_AUTH",
                "discovered_flight_ids": [],
                "discovered_flights": [],
                "playback_status": "NOT_ATTEMPTED",
                "attempt_count": 1,
                "last_attempt_at": "2026-09-25T07:03:00Z",
                "last_error": "auth unavailable",
            }
        ],
    }


def test_p1_status_endpoint_surfaces_blocked_execution_receipt(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    manifest_path = tmp_path / "p1.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(backend, "P1_ACQUISITION_MANIFEST", manifest_path)

    with TestClient(backend.app) as client:
        response = client.get("/api/flight-acquisition/p1/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["target_count"] == 1
    assert body["summary"]["discovery"] == {"BLOCKED_EXTERNAL_AUTH": 1}
    assert body["execution_receipt"]["quota_units_spent"] == 0
    assert body["execution_receipt"]["resumable"] is True
    assert body["next_discovery_target"]["acquisition_id"] == "P1-N1-20260901-20260910"


def test_p1_status_endpoint_returns_404_when_manifest_missing(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    monkeypatch.setattr(backend, "P1_ACQUISITION_MANIFEST", tmp_path / "missing.json")

    with TestClient(backend.app) as client:
        response = client.get("/api/flight-acquisition/p1/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "P1 acquisition manifest not found"
