"""SK-04: municipality positions come from the tracked GNIS gazetteer, not places.geojson."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import fr24.rlsm_anchors as anchors
from fr24.rlsm_gazetteer import Gazetteer

REPO = Path(__file__).resolve().parents[1]

# Generous Puerto Rico bounding box (main island, Vieques, Culebra, Mona).
PR_LAT = (17.8, 18.6)
PR_LON = (-68.0, -65.2)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_78_municipalities_inside_puerto_rico():
    centroids = anchors.municipality_centroids()
    assert len(centroids) == 78
    for name, (lat, lon) in centroids.items():
        assert PR_LAT[0] < lat < PR_LAT[1], name
        assert PR_LON[0] < lon < PR_LON[1], name
    assert "Bayamón" in centroids and "Añasco" in centroids
    assert not any(name.endswith("Municipio") for name in centroids)


def test_empty_gazetteer_fails_closed(monkeypatch):
    monkeypatch.setattr(anchors, "load_gazetteer", lambda: Gazetteer({}))
    with pytest.raises(RuntimeError, match="no municipio rows"):
        anchors.municipality_centroids()


def test_spatial_map_loads_without_places_geojson():
    assert not (REPO / "data" / "places.geojson").exists()
    poi_geo = _load_script("rlsm_spatial_map")._load_poi_geo()
    assert poi_geo["BAYAMÓN"] == poi_geo["BAYAMON"]
    assert poi_geo["BAYAMON"][2] == "municipality"
    assert sum(1 for v in poi_geo.values() if v[2] == "municipality") >= 78


def test_diacritic_repoi_municipality_names_without_places_geojson():
    names = _load_script("rlsm_diacritic_repoi")._municipality_names_by_ascii()
    assert len(names) == 78
    assert names["ANASCO"] == "AÑASCO"
    assert names["MAYAGUEZ"] == "MAYAGÜEZ"
