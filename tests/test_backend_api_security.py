from fastapi.testclient import TestClient

from server.backend import main

client = TestClient(main.app)


def setup_function():
    main.REVIEW_STORE.clear()
    main.clear_artifact_caches()
    main._WRITE_ENABLED = False
    main._WRITE_TOKEN = ""


def enable():
    main._WRITE_ENABLED = True
    main._WRITE_TOKEN = "secret-token"


def test_unknown_entity_and_page_bound():
    assert client.get("/api/entities/NotARealEntity").status_code == 404
    assert client.get("/api/entities/PRAirports?limit=1001").status_code == 422


def test_write_authentication():
    assert client.post("/api/entities/ManualReviewItems", json={"status": "open"}).status_code == 403
    main._WRITE_ENABLED = True
    assert client.post("/api/entities/ManualReviewItems", json={"status": "open"}).status_code == 503
    main._WRITE_TOKEN = "secret-token"
    assert client.post("/api/entities/ManualReviewItems", json={"status": "open"}).status_code == 401


def test_server_owned_ids_and_repeat_patch():
    enable()
    headers = {"Authorization": "Bearer secret-token"}
    assert client.post(
        "/api/entities/ManualReviewItems",
        json={"id": "client"},
        headers=headers,
    ).status_code == 422
    created = client.post(
        "/api/entities/ManualReviewItems",
        json={"status": "open"},
        headers=headers,
    ).json()
    assert created["id"] != "client"
    assert created["_process_overlay"] is True
    identifier = created["id"]
    assert client.patch(
        f"/api/entities/ManualReviewItems/{identifier}",
        json={"id": "other"},
        headers=headers,
    ).status_code == 422
    assert client.patch(
        f"/api/entities/ManualReviewItems/{identifier}",
        json={"status": "reviewed"},
        headers=headers,
    ).status_code == 200
    second = client.patch(
        f"/api/entities/ManualReviewItems/{identifier}",
        json={"note": "ok"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["status"] == "reviewed"


def test_payload_size_and_deterministic_id():
    enable()
    headers = {"Authorization": "Bearer secret-token"}
    assert client.post(
        "/api/entities/ManualReviewItems",
        json={"blob": "x" * (main.MAX_PAYLOAD_BYTES + 1)},
        headers=headers,
    ).status_code == 422
    row = {"name": "same", "score": 3}
    assert main.with_id([row], "missing")[0]["id"] == main.with_id([dict(row)], "missing")[0]["id"]
    assert [
        row["id"]
        for row in main.sort_rows(
            [{"id": "a", "score": 10}, {"id": "b", "score": 2}],
            "score",
        )
    ] == ["b", "a"]
