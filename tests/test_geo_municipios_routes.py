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
    assert body["unmatched_observations"] == 2
    assert sum(counts.values()) + body["unmatched_observations"] == 5

    norms = {f["properties"]["name"]: f["properties"]["observation_density_norm"] for f in body["features"]}
    assert norms == {"San Juan": 1.0, "Ponce": 0.5}


def test_track_index_empty_without_adsb_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    monkeypatch.setattr(backend, "ADSB_DB", tmp_path / "no-such.db")

    with TestClient(backend.app) as client:
        resp = client.get("/api/geo/tracks")
    assert resp.status_code == 200
    assert resp.json() == []
