from __future__ import annotations

from fastapi.testclient import TestClient

from server.backend.main import app
from skywatcher.core.spacetrack import SpaceTrackStore


def test_space_track_status_is_read_only_and_blocked_without_live_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SKYWATCHER_SPACE_TRACK_ROOT", str(tmp_path))
    client = TestClient(app)

    response = client.get("/api/space-track/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["static_contract"]["state"] == "PASS"
    assert payload["runtime"]["state"] == "BLOCKED"
    assert payload["execution"] == {
        "browser_upstream_calls": False,
        "operator_writes": "HARD_DISABLED",
        "credentials_embedded": False,
        "local_store_present": False,
    }
    assert {row["source_id"] for row in payload["sources"]} >= {
        "satcat",
        "gp",
        "decay",
        "tip",
        "publicfiles",
    }


def test_space_track_status_reads_only_frozen_local_materializations(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SKYWATCHER_SPACE_TRACK_ROOT", str(tmp_path))
    store = SpaceTrackStore(tmp_path)
    store.freeze_materialization(
        "space_objects",
        {
            "object_count": 1,
            "objects": [{"norad_cat_id": "49277"}],
            "contradictions": [],
        },
    )
    store.freeze_materialization(
        "reentry_events",
        {
            "events": [{"norad_cat_id": "49277", "canonical_decay_date": "2022-08-30"}],
            "contradictions": [],
        },
    )

    client = TestClient(app)
    status = client.get("/api/space-track/status").json()
    objects = client.get("/api/space-track/objects").json()
    reentry = client.get("/api/space-track/reentry").json()

    assert status["materializations"]["space_objects"]["object_count"] == 1
    assert status["materializations"]["reentry_events"]["event_count"] == 1
    assert objects["state"] == "AVAILABLE"
    assert objects["objects"][0]["norad_cat_id"] == "49277"
    assert reentry["state"] == "AVAILABLE"
    assert reentry["events"][0]["canonical_decay_date"] == "2022-08-30"
