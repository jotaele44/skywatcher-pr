"""GET /api/space-track/sky/* — read-only Sky Target Finder endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.backend.main import app
from skywatcher.core.spacetrack import SpaceTrackStore
from tests.test_sky_satellites import ISS_2014

AT = "2026-10-20T00:30:00Z"
ISS_AT = "2014-01-23T11:18:07Z"
ISS_SITE = {"lat": 40.8939, "lon": -83.8917, "elev_m": 0}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_SPACE_TRACK_ROOT", str(tmp_path / "absent-store"))
    return TestClient(app)


@pytest.fixture
def frozen_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYWATCHER_SPACE_TRACK_ROOT", str(tmp_path))
    SpaceTrackStore(tmp_path).freeze_materialization(
        "space_objects",
        {
            "object_count": 3,
            "objects": [
                {
                    "norad_cat_id": "25544",
                    "object_id": "1998-067A",
                    "identity_state": "PASS",
                    "aliases": ["ISS (ZARYA)"],
                    "gp_row": {"object_name": "ISS (ZARYA)", "object_type": "PAYLOAD",
                               "raw": ISS_2014},
                },
                {"norad_cat_id": "99999", "identity_state": "PASS", "gp_row": None},
                {
                    "norad_cat_id": "5",
                    "identity_state": "PASS",
                    "aliases": ["VANGUARD 1"],
                    "gp_row": {"object_name": "VANGUARD 1",
                               "raw": {**ISS_2014, "NORAD_CAT_ID": "5", "OBJECT_ID": "1958-002B"}},
                },
            ],
            "contradictions": [],
        },
    )
    return TestClient(app)


def test_targets_search_without_space_track_store(client):
    response = client.get("/api/space-track/sky/targets", params={"q": "East", "at": AT})
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "skywatcher.sky-targets/v1"
    assert payload["at_utc"] == AT
    assert payload["observer"] == {"lat_deg": 18.4655, "lon_deg": -66.1057, "elev_m": 10.0}
    assert payload["satellites"] == {
        "state": "NOT_MATERIALIZED",
        "object_count": None,
        "propagated": 0,
        "skipped_count": 0,
        "skipped": [],
    }
    veil = next(t for t in payload["targets"] if t["id"] == "caldwell:C33")
    assert veil["display"] == "C 33 (East Veil Nebula)"
    assert veil["match"] == {"field": "name", "text": "East Veil Nebula"}
    assert veil["filter_hint"] == {"label": "Duo-Band", "basis": "heuristic"}
    assert veil["above_horizon"] is True and veil["visibility"]["state"] == "UP"
    assert veil["visibility"]["rise_utc"] < AT < veil["visibility"]["set_utc"]
    marfak = next(t for t in payload["targets"] if t["id"] == "star:hip:5542")
    assert marfak["match"]["text"] == "Marfak-East"


def test_targets_without_query_list_visible_objects_brightest_first(client):
    payload = client.get("/api/space-track/sky/targets", params={"at": AT, "limit": 10}).json()
    assert payload["count"] == len(payload["targets"]) == 10
    assert all(t["above_horizon"] for t in payload["targets"])
    magnitudes = [t["magnitude"] for t in payload["targets"]]
    assert magnitudes == sorted(magnitudes)
    assert payload["targets"][0]["id"] == "moon"


def test_default_time_is_now(client):
    response = client.get("/api/space-track/sky/targets", params={"q": "Vega"})
    assert response.status_code == 200
    assert response.json()["at_utc"].endswith("Z")


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/space-track/sky/targets", {"lat": 91}),
        ("/api/space-track/sky/targets", {"lon": -181}),
        ("/api/space-track/sky/targets", {"kind": "bogus"}),
        ("/api/space-track/sky/targets", {"limit": 0}),
        ("/api/space-track/sky/targets", {"at": "not-a-time"}),
        ("/api/space-track/sky/recommend", {"at": "2026-13-40"}),
        ("/api/space-track/sky/targets", {"at": "9999-12-31T23:59:00Z"}),
        ("/api/space-track/sky/chart", {"target": "caldwell:C33", "fov_deg": 0.1}),
        ("/api/space-track/sky/chart", {}),
    ],
)
def test_invalid_parameters_are_rejected(client, path, params):
    assert client.get(path, params=params).status_code == 422


def test_unknown_chart_target_is_404(client):
    response = client.get("/api/space-track/sky/chart", params={"target": "caldwell:C999"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown sky target: caldwell:C999"


def test_chart_payload_for_the_veil(client):
    payload = client.get(
        "/api/space-track/sky/chart", params={"target": "caldwell:C33", "at": AT}
    ).json()
    assert payload["schema_version"] == "skywatcher.sky-chart/v1"
    assert (payload["fov_deg"], payload["radius_deg"], payload["limiting_magnitude"]) == (
        6.0,
        12.0,
        7.5,
    )
    assert payload["target"]["long_designation"] == "Caldwell 33"
    labels = {star["label"] for star in payload["stars"] if star["label"]}
    assert "Epsilon Cygni" in labels
    assert any(star["id"] is None for star in payload["stars"])  # deep layer included
    assert {m["id"] for m in payload["dso_markers"]} >= {"caldwell:C34"}
    assert all(m["id"] != "caldwell:C33" for m in payload["dso_markers"])
    assert any(line["constellation"] == "Cyg" for line in payload["lines"])
    wide = client.get(
        "/api/space-track/sky/chart", params={"target": "caldwell:C33", "at": AT, "fov_deg": 30}
    ).json()
    assert wide["limiting_magnitude"] == 6.0
    assert all(star["id"] is not None for star in wide["stars"])


def test_recommend_ranks_tonights_targets(client):
    payload = client.get("/api/space-track/sky/recommend", params={"at": AT}).json()
    assert payload["schema_version"] == "skywatcher.sky-recommend/v1"
    window = payload["dark_window"]
    assert window["sun_alt_deg"] == -12.0
    assert window["start_utc"] < AT < window["end_utc"]
    targets = payload["targets"]
    assert 0 < len(targets) <= 20
    scores = [t["recommend"]["score"] for t in targets]
    assert scores == sorted(scores, reverse=True)
    assert all(t["recommend"]["best_alt_deg"] >= 30.0 for t in targets)
    assert all(t["kind"] in ("messier", "caldwell", "planet", "moon") for t in targets)


def test_frozen_satellites_are_propagated(frozen_client):
    payload = frozen_client.get(
        "/api/space-track/sky/targets",
        params={"q": "ISS", "kind": "satellite", "at": ISS_AT, **ISS_SITE},
    ).json()
    assert payload["satellites"]["state"] == "AVAILABLE"
    assert payload["satellites"]["object_count"] == 3
    assert payload["satellites"]["propagated"] == 1  # only the name match is propagated
    assert payload["satellites"]["skipped"] == [
        {"norad_cat_id": "99999", "reason": "no current GP elements"}
    ]
    iss = payload["targets"][0]
    assert iss["id"] == "satellite:norad:25544"
    assert iss["display"] == "ISS (ZARYA)" and iss["object_type"] == "payload"
    assert iss["satellite"]["norad_cat_id"] == "25544"
    assert iss["satellite"]["identity_state"] == "PASS"
    assert abs(iss["satellite"]["range_km"] - 1168.7) < 0.5
    assert abs(iss["az_deg"] - 350.26) < 0.05

    chart = frozen_client.get(
        "/api/space-track/sky/chart",
        params={"target": "satellite:norad:25544", "at": ISS_AT, **ISS_SITE},
    )
    assert chart.status_code == 200
    assert chart.json()["target"]["id"] == "satellite:norad:25544"


def test_stale_elements_are_skipped(frozen_client):
    payload = frozen_client.get(
        "/api/space-track/sky/targets", params={"kind": "satellite", "at": AT}
    ).json()
    assert payload["satellites"]["propagated"] == 0
    assert any("days from epoch" in item["reason"] for item in payload["satellites"]["skipped"])


def test_propagation_is_limited_to_what_can_be_returned(frozen_client):
    common = {"at": ISS_AT, **ISS_SITE}
    everything = frozen_client.get(
        "/api/space-track/sky/targets", params={"kind": "satellite", **common}
    ).json()
    assert everything["satellites"]["propagated"] == 2
    by_norad = frozen_client.get(
        "/api/space-track/sky/targets", params={"q": "5", "kind": "satellite", **common}
    ).json()
    # "5" is also a substring of 25544; the exact NORAD id still ranks first.
    assert [t["id"] for t in by_norad["targets"]] == ["satellite:norad:5", "satellite:norad:25544"]
    by_name = frozen_client.get(
        "/api/space-track/sky/targets", params={"q": "vanguard", "kind": "satellite", **common}
    ).json()
    assert by_name["satellites"]["propagated"] == 1
    assert [t["display"] for t in by_name["targets"]] == ["VANGUARD 1"]
    messier_only = frozen_client.get(
        "/api/space-track/sky/targets", params={"q": "M 31", "kind": "messier", **common}
    ).json()
    assert messier_only["satellites"]["state"] == "AVAILABLE"
    assert messier_only["satellites"]["propagated"] == 0
