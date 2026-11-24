"""Pinned Puerto Rico route-number parser (authority: spiderweb-pr).

Fails if federation/roads/pr_route_ref.py is edited locally (the checksum no
longer matches the pin) or if its behaviour drifts from the authority's tests.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADS = ROOT / "federation" / "roads"
sys.path.insert(0, str(ROADS))

import pr_route_ref as r  # noqa: E402

PIN = json.loads((ROADS / "pr_route_ref.pin.json").read_text(encoding="utf-8"))


def test_module_matches_pin():
    digest = hashlib.sha256((ROOT / PIN["module_path"]).read_bytes()).hexdigest()
    assert digest == PIN["module_sha256"], "pr_route_ref.py differs from its pin; re-extract it from spiderweb-pr instead of editing it"
    assert PIN["authority_repository"] == "jotaele44/spiderweb-pr"
    assert PIN["compatibility_policy"] == "FAIL_CLOSED"
    for name in PIN["extracted_symbols"]:
        assert hasattr(r, name), name


def test_band_edges():
    assert [r.route_number_band(n) for n in ("1", "99", "100", "299", "300", "9999")] == [
        "primary_band", "primary_band", "secondary_band", "secondary_band", "tertiary_band", "tertiary_band"]
    assert r.route_number_band("0") == "unknown"
    assert r.route_number_band(None) == "unknown"


def test_spellings_and_ramal():
    assert r.parse_route_ref("Carretera 191")["route_number_band"] == "secondary_band"
    assert r.parse_route_ref("Route PR-303")["route_number_band"] == "tertiary_band"
    assert r.parse_route_ref("Puerto Rico Highway 52")["route_number_band"] == "primary_band"
    ref = r.parse_route_ref("Carr. 3R Km 12.4")
    assert (ref["route_number"], ref["base_number"], ref["is_ramal"], ref["km"]) == ("3R", "3", True, 12.4)
    assert r.parse_route_ref("Calle Luna")["route_number"] == ""


def test_km_markers():
    assert r.km_marker_from_text("Carr. 3 Km 5 Hm 2") == 5.2
    assert r.km_marker_from_text("PR-2 km 10,5") == 10.5
    assert r.km_marker_from_text("PR-2") is None
