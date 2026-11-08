"""Sky Cameras API: public catalog, quarantined intake, guarded review, approved-only media."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.backend.main as backend
from server.backend import cameras_router

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64
LINK = {
    "kind": "camera_link",
    "title": "Playa Jobos cam",
    "url": "https://example.org/jobos-live",
    "categories": "beach,sky",
    "municipality": "Isabela",
    "license": "display-only",
    "attest_rights": "true",
    "attest_consent": "true",
    "contact": "me@example.org",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_ROOT", str(tmp_path))
    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR", "0")
    # TestClient's peer is "testclient", not a local address, so review uses the token path.
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "test-token")
    cameras_router._rate_hits.clear()
    return TestClient(backend.app, headers={"Authorization": "Bearer test-token"})


def _submit(client, data=None, files=None):
    return client.post("/api/sky-cameras/submissions", data=data or LINK, files=files)


def test_catalog_lists_curated_cameras(client):
    body = client.get("/api/sky-cameras").json()
    assert body["count"] >= 1
    assert len(body["municipios"]) == 78
    first = body["cameras"][0]
    assert {"id", "page_url", "embed_url", "status", "checked_at"} <= set(first)
    beaches = client.get("/api/sky-cameras", params={"category": "beach"}).json()
    assert all("beach" in camera["categories"] for camera in beaches["cameras"])
    assert client.get("/api/sky-cameras", params={"category": "volcano"}).status_code == 422


def test_coverage_reports_gaps(client):
    body = client.get("/api/sky-cameras/coverage").json()
    assert body["municipio_total"] == 78
    assert body["municipios_covered"] >= 1
    assert "river" in body["categories_without_cameras"]


def test_link_submission_is_quarantined_until_approved(client):
    response = _submit(client)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["status"] == "pending"
    assert "contact" not in receipt
    names = [camera["name"] for camera in client.get("/api/sky-cameras").json()["cameras"]]
    assert "Playa Jobos cam" not in names

    queue = client.get("/api/sky-cameras/submissions").json()
    assert queue["count"] == 1 and queue["submissions"][0]["contact"] == "me@example.org"

    decided = client.post(
        f"/api/sky-cameras/submissions/{receipt['id']}/decision", json={"decision": "approved"}
    )
    assert decided.status_code == 200
    listed = [c for c in client.get("/api/sky-cameras").json()["cameras"] if c["name"] == "Playa Jobos cam"]
    assert listed and listed[0]["added_by"] == "community"
    assert listed[0]["embed_url"] is None  # third-party camera links are never embedded
    assert "contact" not in listed[0]


def test_own_youtube_video_is_embedded_after_approval(client):
    data = {**LINK, "kind": "video_link", "title": "Sunset over Rincón", "url": "https://youtu.be/abcdefghijk",
            "municipality": "Rincón", "license": "cc-by-4.0", "contributor": "Ana"}
    receipt = _submit(client, data).json()
    client.post(f"/api/sky-cameras/submissions/{receipt['id']}/decision", json={"decision": "approved"})
    camera = next(c for c in client.get("/api/sky-cameras").json()["cameras"] if c["name"] == "Sunset over Rincón")
    assert camera["embed_url"] == "https://www.youtube-nocookie.com/embed/abcdefghijk"
    assert camera["contributor"] == "Ana"


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"attest_rights": ""}, "publicly available"),
        ({"attest_consent": "false"}, "consent"),
        ({"url": "http://example.org/cam"}, "https://"),
        ({"categories": "volcano"}, "unknown category"),
        ({"municipality": "Gotham"}, "78 municipalities"),
        ({"license": "mine"}, "license"),
        ({"title": ""}, "title"),
        ({"lat": "18.4"}, "latitude and longitude"),
        ({"lat": "40", "lon": "-74"}, "Puerto Rico"),
    ],
)
def test_submission_validation(client, override, fragment):
    response = _submit(client, {**LINK, **override})
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_upload_lifecycle(client, tmp_path):
    data = {**LINK, "kind": "video_upload", "title": "Storm over Cayey", "municipality": "Cayey"}
    data.pop("url")
    response = _submit(client, data, files={"file": ("storm.mp4", MP4, "video/mp4")})
    assert response.status_code == 201, response.text
    submission_id = response.json()["id"]

    assert client.get(f"/api/sky-cameras/media/{submission_id}").status_code == 404  # pending
    preview = client.get(f"/api/sky-cameras/submissions/{submission_id}/media")
    assert preview.status_code == 200 and preview.content == MP4

    client.post(f"/api/sky-cameras/submissions/{submission_id}/decision", json={"decision": "approved"})
    media = client.get(f"/api/sky-cameras/media/{submission_id}")
    assert media.status_code == 200 and media.headers["content-type"] == "video/mp4"
    camera = next(c for c in client.get("/api/sky-cameras").json()["cameras"] if c["name"] == "Storm over Cayey")
    assert camera["media_url"] == f"/api/sky-cameras/media/{submission_id}"

    removed = client.post(f"/api/sky-cameras/submissions/{submission_id}/decision", json={"decision": "removed"})
    assert removed.status_code == 200
    assert client.get(f"/api/sky-cameras/media/{submission_id}").status_code == 404
    assert not list((tmp_path / "uploads").glob(f"{submission_id}*"))
    names = [c["name"] for c in client.get("/api/sky-cameras").json()["cameras"]]
    assert "Storm over Cayey" not in names


def test_upload_rejects_non_video_and_oversize(client, monkeypatch, tmp_path):
    data = {**LINK, "kind": "video_upload"}
    data.pop("url")
    bad = _submit(client, data, files={"file": ("x.mp4", b"<html><script>alert(1)</script>", "video/mp4")})
    assert bad.status_code == 422 and "MP4, MOV or WebM" in bad.json()["detail"]

    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_MAX_UPLOAD_MB", "1")
    big = _submit(client, data, files={"file": ("big.mp4", MP4 + b"\x00" * (3 * 1024 * 1024), "video/mp4")})
    assert big.status_code == 413
    uploads = tmp_path / "uploads"
    assert not uploads.exists() or not [p for p in uploads.iterdir() if p.is_file()]


def test_upload_needs_file_and_links_need_no_file(client):
    data = {**LINK, "kind": "video_upload"}
    data.pop("url")
    assert _submit(client, data).status_code == 422
    assert _submit(client, LINK, files={"file": ("a.mp4", MP4, "video/mp4")}).status_code == 422


def test_reviewer_routes_require_write_token(client):
    anonymous = TestClient(backend.app)
    assert anonymous.get("/api/sky-cameras/submissions").status_code == 401
    assert anonymous.post("/api/sky-cameras/submissions/x/decision", json={"decision": "approved"}).status_code == 401
    # Public intake still works without the token.
    assert _submit(anonymous).status_code == 201
    authed = client.get("/api/sky-cameras/submissions")
    assert authed.status_code == 200 and authed.json()["count"] == 1


def test_rate_limit(client, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_SKY_CAMERAS_SUBMISSIONS_PER_HOUR", "2")
    assert _submit(client).status_code == 201
    assert _submit(client).status_code == 201
    assert _submit(client).status_code == 429


def test_unknown_submission(client):
    assert client.post("/api/sky-cameras/submissions/nope/decision", json={"decision": "approved"}).status_code == 404
    assert client.get("/api/sky-cameras/media/../../etc").status_code == 404


def test_reviewer_guard_fails_closed_without_the_app_override(client):
    from fastapi import FastAPI

    bare = FastAPI()
    bare.include_router(cameras_router.router)
    assert TestClient(bare).get("/api/sky-cameras/submissions").status_code == 503
