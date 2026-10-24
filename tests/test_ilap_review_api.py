from __future__ import annotations

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
    backend._created.clear()
    backend._overlay.clear()
    return backend


def test_ilap_review_fails_closed_without_evidence():
    from starlette.testclient import TestClient
    backend = _backend()
    with TestClient(backend.app) as client:
        body = client.get("/api/ilap/review").json()
    assert body["candidate"] is None
    assert body["frames"] == []
    assert body["comparisons"] == []
    assert body["availability"] == {"candidate": "OPEN", "frames": "OPEN", "annotations": "OPEN", "comparisons": "OPEN"}
    assert body["guardrails"]["synthetic_evidence"] is False
    assert body["guardrails"]["source_imagery_immutable"] is True


def test_ilap_annotation_is_session_scoped_and_does_not_mutate_evidence(monkeypatch):
    from starlette.testclient import TestClient
    backend = _backend()
    monkeypatch.setattr(backend, "_is_local_network", lambda host: host == "testclient")
    payload = {"candidate_id": "candidate-1", "source_frame_id": "frame-1", "class_name": "vegetation_palm", "actor_type": "HUMAN", "evidence_state": "REVIEW_UNRESOLVED", "coordinate_space": "FRAME_UNBOUND", "geometry": None, "derived_annotation": True}
    with TestClient(backend.app) as client:
        before = client.get("/api/ilap/review").json()
        created = client.post("/api/entities/ILAPReviewAnnotations", json=payload)
        after = client.get("/api/ilap/review").json()
    assert created.status_code == 200
    assert before["candidate"] is None and after["candidate"] is None
    assert before["frames"] == [] and after["frames"] == []
    assert after["availability"]["annotations"] == "AVAILABLE"
    assert after["annotations"][0]["derived_annotation"] is True
    assert after["annotations"][0]["geometry"] is None


def test_ilap_annotation_rejects_nonlocal_client_without_token(monkeypatch):
    from starlette.testclient import TestClient
    backend = _backend()
    monkeypatch.setattr(backend, "_is_local_network", lambda host: False)
    with TestClient(backend.app) as client:
        response = client.post("/api/entities/ILAPReviewAnnotations", json={"candidate_id": "candidate-1", "derived_annotation": True})
    assert response.status_code == 403
