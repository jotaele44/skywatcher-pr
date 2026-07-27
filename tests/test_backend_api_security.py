from __future__ import annotations

from fastapi.testclient import TestClient

from server.backend import main


client = TestClient(main.app)


def setup_function():
    main.REVIEW_STORE.clear()
    main.clear_artifact_caches()
    main._WRITE_ENABLED = False
    main._WRITE_TOKEN = ""


def test_unknown_entity_is_not_silently_empty():
    response = client.get("/api/entities/NotARealEntity")
    assert response.status_code == 404


def test_page_size_is_bounded():
    response = client.get("/api/entities/PRAirports?limit=1001")
    assert response.status_code == 422


def test_writes_are_disabled_by_default():
    response = client.post("/api/entities/ManualReviewItems", json={"status": "open"})
    assert response.status_code == 403


def test_enabled_writes_require_configured_token():
    main._WRITE_ENABLED = True
    response = client.post("/api/entities/ManualReviewItems", json={"status": "open"})
    assert response.status_code == 503


def test_enabled_writes_require_matching_bearer_token():
    main._WRITE_ENABLED = True
    main._WRITE_TOKEN = "secret-token"
    denied = client.post("/api/entities/ManualReviewItems", json={"status": "open"})
    assert denied.status_code == 401
    created = client.post(
        "/api/entities/ManualReviewItems",
        json={"status": "open"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert created.status_code == 200
    assert created.json()["_process_overlay"] is True


def test_source_id_fallback_is_deterministic():
    row = {"name": "same", "score": 3}
    first = main.with_id([row], "missing")[0]["id"]
    second = main.with_id([dict(row)], "missing")[0]["id"]
    assert first == second


def test_numeric_sort_is_numeric_not_lexical():
    rows = [{"id": "a", "score": 10}, {"id": "b", "score": 2}]
    assert [row["id"] for row in main.sort_rows(rows, "score")] == ["b", "a"]
