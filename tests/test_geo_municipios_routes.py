"""Municipios boundary + observation-density GeoJSON routes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from server.backend import main as backend

FIXTURE = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"name": "San Juan", "geoid": "72127"}, "geometry": None},
        {"type": "Feature", "properties": {"name": "Ponce", "geoid": "72113"}, "geometry": None},
    ],
}


def _write_fixture(path: Path) -> None:
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")


def test_municipios_route_serves_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    fixture_path = tmp_path / "municipios.json"
    _write_fixture(fixture_path)
    monkeypatch.setattr(backend, "MUNICIPIOS_PATH", fixture_path)

    with TestClient(backend.app) as client:
        resp = client.get("/api/geo/municipios.geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 2


def test_municipios_route_missing_file_returns_empty_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.testclient import TestClient

    monkeypatch.setattr(backend, "MUNICIPIOS_PATH", tmp_path / "does-not-exist.json")

    with TestClient(backend.app) as client:
        resp = client.get("/api/geo/municipios.geojson")
    assert resp.status_code == 200
    assert resp.json() == {"type": "FeatureCollection", "features": []}


def test_observation_density_reconciles_against_loaded_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """by-feature counts plus unmatched must equal the total observation
    count, the same reconciliation invariant used for aguayluz-pr's
    event_density and spiderweb-pr's gazetteer density endpoints."""
    from starlette.testclient import TestClient

    fixture_path = tmp_path / "municipios.json"
    _write_fixture(fixture_path)
    monkeypatch.setattr(backend, "MUNICIPIOS_PATH", fixture_path)
    monkeypatch.setattr(
        backend,
        "load_observations",
        lambda: [
            {"municipality": "San Juan"},
            {"municipality": "San Juan"},
            {"municipality": "Ponce"},
            {"municipality": "Not A Real Municipio"},
            {},
        ],
    )

    with TestClient(backend.app) as client:
        resp = client.get("/api/geo/municipios/observation_density.geojson")
    assert resp.status_code == 200
    body = resp.json()

    counts = {f["properties"]["name"]: f["properties"]["observation_count"] for f in body["features"]}
    assert counts == {"San Juan": 2, "Ponce": 1}
    assert body["matched_count"] == 3
    assert body["unmatched_observations"] == 2
    assert body["unresolved_by_name"] == {"<NULL>": 1, "Not A Real Municipio": 1}
    assert body["total_observations"] == 5
    assert sum(counts.values()) + body["unmatched_observations"] == 5
    assert body["ambiguous_municipio_candidates"] == {}
    assert body["scope"]["identity_effect"] == "NONE"
    assert body["scope"]["binding_effect"] == "AGGREGATION_ONLY"
    assert body["provenance"]["sources"]["municipios"]["sha256"]
    assert body["provenance"]["sources"]["municipios"]["snapshot_stable_during_hash"] is True
    assert body["provenance"]["sources"]["municipios"]["logical_snapshot_bound"] is True
    assert body["provenance"]["sources"]["rlsm_observations"]["declared_mutable"] is True
    assert body["provenance"]["sources"]["rlsm_observations"]["logical_snapshot_bound"] is False

    norms = {f["properties"]["name"]: f["properties"]["observation_density_norm"] for f in body["features"]}
    assert norms == {"San Juan": 1.0, "Ponce": 0.5}


def test_observation_density_keeps_duplicate_name_candidates_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.testclient import TestClient

    fixture_path = tmp_path / "municipios.json"
    fixture = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "San Juan", "geoid": "72127"}, "geometry": None},
            {"type": "Feature", "properties": {"name": "San Juan", "geoid": "72999"}, "geometry": None},
            {"type": "Feature", "properties": {"name": "Ponce", "geoid": "72113"}, "geometry": None},
        ],
    }
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(backend, "MUNICIPIOS_PATH", fixture_path)
    monkeypatch.setattr(
        backend,
        "load_observations",
        lambda: [{"municipality": "San Juan"}, {"municipality": "Ponce"}],
    )

    with TestClient(backend.app) as client:
        body = client.get("/api/geo/municipios/observation_density.geojson").json()

    assert [feature["properties"]["observation_count"] for feature in body["features"]] == [0, 0, 1]
    assert body["matched_count"] == 1
    assert body["unmatched_observations"] == 1
    assert body["unresolved_by_name"] == {"San Juan": 1}
    assert body["ambiguous_municipio_candidates"] == {
        "San Juan": [
            {"feature_index": 0, "geoid": "72127"},
            {"feature_index": 1, "geoid": "72999"},
        ]
    }


def test_track_index_empty_without_adsb_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    monkeypatch.setattr(backend, "ADSB_DB", tmp_path / "no-such.db")

    with TestClient(backend.app) as client:
        resp = client.get("/api/geo/tracks")
    assert resp.status_code == 200
    assert resp.json() == []
