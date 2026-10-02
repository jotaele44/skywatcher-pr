"""Gate: Flight Archive API persists exact source bytes under the write guard."""

from __future__ import annotations

import base64
import hashlib
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


def _record() -> dict:
    return {
        "corpusUid": "mfl:test",
        "monthBucket": "2026-09",
        "sourceFlightIdRaw": "deadbeef",
        "callsignRaw": "N1",
        "pointCount": 1,
        "startTimeUtc": "2026-09-24T00:00:00.000Z",
        "endTimeUtc": "2026-09-24T00:00:01.000Z",
        "start": {"lat": 18.1, "lon": -66.1},
        "end": {"lat": 18.1, "lon": -66.1},
        "sourceManifestations": [],
        "raw": {"h": "test", "fid": "deadbeef", "cs": "N1", "n": 1},
    }


def _payload(source: bytes) -> dict:
    return {
        "source_bytes_base64": base64.b64encode(source).decode("ascii"),
        "source_kind": "master_flight_log_html",
        "source_filename": "Master Flight Log.html",
        "format_name": "master-flight-log-backup",
        "format_version": 1,
        "records": [_record()],
    }


def test_archive_get_does_not_create_missing_database(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    dbp = tmp_path / "absent.db"
    monkeypatch.setattr(backend, "ADSB_DB", dbp)

    with TestClient(backend.app) as client:
        response = client.get("/api/flight-corpus/archive/snapshots")

    assert response.status_code == 200
    assert response.json() == []
    assert not dbp.exists()


def test_archive_post_hashes_exact_bytes_and_is_idempotent(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    dbp = tmp_path / "corpus.db"
    source = b"\x00MFL\r\nexact-bytes\xff"
    monkeypatch.setattr(backend, "ADSB_DB", dbp)
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "test-token")

    headers = {"Authorization": "Bearer test-token"}
    with TestClient(backend.app) as client:
        first = client.post(
            "/api/flight-corpus/archive/snapshots",
            headers=headers,
            json=_payload(source),
        )
        second = client.post(
            "/api/flight-corpus/archive/snapshots",
            headers=headers,
            json=_payload(source),
        )
        listed = client.get("/api/flight-corpus/archive/snapshots")
        detail = client.get(
            f"/api/flight-corpus/archive/snapshots/{first.json()['snapshot_id']}"
        )

    assert first.status_code == 200, first.text
    assert first.json()["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert first.json()["duplicate_snapshot"] is False
    assert second.status_code == 200, second.text
    assert second.json()["snapshot_id"] == first.json()["snapshot_id"]
    assert second.json()["duplicate_snapshot"] is True
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["record_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["snapshot"]["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert len(detail.json()["records"]) == 1
    assert detail.json()["records"][0]["corpusUid"] == "mfl:test"
    assert detail.json()["records"][0]["raw"]["fid"] == "deadbeef"


def test_archive_post_requires_write_authorization(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    monkeypatch.setattr(backend, "ADSB_DB", tmp_path / "corpus.db")
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "required-token")

    with TestClient(backend.app) as client:
        response = client.post(
            "/api/flight-corpus/archive/snapshots",
            json=_payload(b"source"),
        )

    assert response.status_code == 401


def test_archive_post_rejects_invalid_base64_without_creating_db(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    dbp = tmp_path / "corpus.db"
    monkeypatch.setattr(backend, "ADSB_DB", dbp)
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "test-token")

    payload = _payload(b"source")
    payload["source_bytes_base64"] = "%%%not-base64%%%"
    with TestClient(backend.app) as client:
        response = client.post(
            "/api/flight-corpus/archive/snapshots",
            headers={"Authorization": "Bearer test-token"},
            json=payload,
        )

    assert response.status_code == 400
    assert not dbp.exists()


def test_archive_coverage_endpoint_returns_bounded_ledger(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    dbp = tmp_path / "corpus.db"
    monkeypatch.setattr(backend, "ADSB_DB", dbp)
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "test-token")

    payload = _payload(b"coverage-source")
    payload["records"] = [
        {
            **_record(),
            "corpusUid": "mfl:a",
            "sourceFlightIdRaw": "00000001",
            "callsignRaw": "N1",
            "pointCount": 20,
            "startTimeUtc": "2026-07-01T12:00:00.000Z",
            "endTimeUtc": "2026-07-01T13:00:00.000Z",
            "sourceManifestations": [{"folderRaw": "N1", "filenameRaw": "a.csv", "kmlPresent": True}],
        },
        {
            **_record(),
            "corpusUid": "mfl:b",
            "sourceFlightIdRaw": "00000002",
            "callsignRaw": "N1",
            "pointCount": 20,
            "startTimeUtc": "2026-07-02T12:00:00.000Z",
            "endTimeUtc": "2026-07-02T13:00:00.000Z",
            "sourceManifestations": [{"folderRaw": "N1", "filenameRaw": "b.csv", "kmlPresent": True}],
        },
        {
            **_record(),
            "corpusUid": "mfl:c",
            "sourceFlightIdRaw": "00000003",
            "callsignRaw": "N1",
            "pointCount": 20,
            "startTimeUtc": "2026-07-03T12:00:00.000Z",
            "endTimeUtc": "2026-07-03T13:00:00.000Z",
            "sourceManifestations": [{"folderRaw": "N1", "filenameRaw": "c.csv", "kmlPresent": True}],
        },
        {
            **_record(),
            "corpusUid": "mfl:d",
            "sourceFlightIdRaw": "00000004",
            "callsignRaw": "N1",
            "pointCount": 20,
            "startTimeUtc": "2026-08-20T12:00:00.000Z",
            "endTimeUtc": "2026-08-20T13:00:00.000Z",
            "sourceManifestations": [{"folderRaw": "N1", "filenameRaw": "d.csv", "kmlPresent": False}],
        },
    ]

    headers = {"Authorization": "Bearer test-token"}
    with TestClient(backend.app) as client:
        persisted = client.post(
            "/api/flight-corpus/archive/snapshots",
            headers=headers,
            json=payload,
        )
        snapshot_id = persisted.json()["snapshot_id"]
        response = client.get(
            f"/api/flight-corpus/archive/snapshots/{snapshot_id}/coverage",
            params={"as_of": "2026-09-25"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot"]["snapshot_id"] == snapshot_id
    assert body["summary"]["input_records"] == 4
    assert body["summary"]["identity_count"] == 5
    assert body["summary"]["source_callsign_identity_count"] == 1
    assert body["summary"]["watchlist_only_identity_count"] == 4
    assert body["summary"]["gap_count"] == 1
    assert body["gaps"][0]["state"] == "RECOVERABLE"
    assert body["summary"]["missing_kml_record_count"] == 1
    assert any(item["type"] == "KML" for item in body["acquisition_queue"])


def test_archive_coverage_endpoint_rejects_bad_as_of(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    backend = _backend()
    dbp = tmp_path / "corpus.db"
    monkeypatch.setattr(backend, "ADSB_DB", dbp)
    monkeypatch.setattr(backend, "_WRITE_TOKEN", "test-token")

    with TestClient(backend.app) as client:
        persisted = client.post(
            "/api/flight-corpus/archive/snapshots",
            headers={"Authorization": "Bearer test-token"},
            json=_payload(b"coverage-source"),
        )
        response = client.get(
            f"/api/flight-corpus/archive/snapshots/{persisted.json()['snapshot_id']}/coverage",
            params={"as_of": "not-a-date"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "as_of must be YYYY-MM-DD"
