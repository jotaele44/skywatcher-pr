from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spatial = _load("rlsm_spatial_map", ROOT / "scripts" / "rlsm_spatial_map.py")
network = _load("rlsm_network_graph", ROOT / "scripts" / "rlsm_network_graph.py")


def _assert_self_contained(html: str) -> None:
    lowered = html.lower()
    assert "<script src=" not in lowered
    assert "<link rel=\"stylesheet\" href=" not in lowered
    assert "https://" not in lowered
    without_svg_namespace = lowered.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in without_svg_namespace
    assert "unpkg.com" not in lowered
    assert "tile.openstreetmap.org" not in lowered


def test_spatial_report_is_self_contained_and_preserves_data() -> None:
    pois = [
        {
            "name": "SAN JUAN </script>",
            "lat": 18.42,
            "lon": -66.07,
            "type": "municipality",
            "sightings": 4,
            "top_operator": "PREPA",
            "top_aircraft": "N1(4)",
            "n_aircraft": 1,
        }
    ]
    gaps = ["BAYAMON"]
    geography = {"BAYAMON": (18.39, -66.16, "municipality")}
    html = spatial.render_spatial_html(pois, gaps, geography)
    _assert_self_contained(html)
    assert "SAN JUAN <\\/script>" in html
    assert "BAYAMON" in html
    assert "companion GeoJSON" in html


def test_network_report_is_self_contained_and_deterministic() -> None:
    nodes = [
        {
            "id": "N1",
            "label": "N1",
            "owner": "Owner",
            "model": "Model",
            "sightings": 3,
            "degree": 1,
            "value": 5,
            "community_id": 0,
            "color": "#1f77b4",
        },
        {
            "id": "N2",
            "label": "N2",
            "owner": "Owner 2",
            "model": "Model 2",
            "sightings": 2,
            "degree": 1,
            "value": 5,
            "community_id": 0,
            "color": "#1f77b4",
        },
    ]
    edges = [{"from": "N1", "to": "N2", "value": 2, "title": "2 co-occurrences"}]
    first = network.render_network_html(nodes, edges, window_min=10, min_cooccur=2)
    second = network.render_network_html(nodes, edges, window_min=10, min_cooccur=2)
    _assert_self_contained(first)
    assert first == second
    assert "N1" in first and "N2" in first
    assert "2 co-occurrences" in first
