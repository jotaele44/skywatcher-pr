"""The vendored sky catalog (data/reference/sky) is complete, pinned and self-consistent."""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKY_DIR = ROOT / "data" / "reference" / "sky"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_sky_catalog", ROOT / "scripts" / "build_sky_catalog.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict:
    return json.loads((SKY_DIR / "sky_catalog.v1.json").read_text(encoding="utf-8"))


def _separation(ra1, dec1, ra2, dec2):
    a1, d1, a2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    cos_c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_c))))


def test_committed_outputs_verify_offline():
    assert _builder().verify_outputs(SKY_DIR) == []


def test_verify_rejects_a_corrupted_catalog(tmp_path):
    for name in ("sky_catalog.v1.json", "sky_stars_deep.v1.json"):
        shutil.copy(SKY_DIR / name, tmp_path / name)
    catalog = json.loads((tmp_path / "sky_catalog.v1.json").read_text(encoding="utf-8"))
    catalog["deep_sky"] = [item for item in catalog["deep_sky"] if item["id"] != "caldwell:C99"]
    catalog["star_names"]["102488"]["bayer"] = "undefined3"
    (tmp_path / "sky_catalog.v1.json").write_text(json.dumps(catalog), encoding="utf-8")

    errors = _builder().verify_outputs(tmp_path)

    assert "Caldwell set is not exactly C1..C109" in errors
    assert any("corrupt Bayer token" in error for error in errors)
    assert "outputs are not in canonical serialization" in errors


def test_messier_and_caldwell_sets_are_exact():
    deep_sky = _catalog()["deep_sky"]
    ids = {item["id"] for item in deep_sky}
    assert {f"messier:M{n}" for n in range(1, 111)} <= ids
    assert {f"caldwell:C{n}" for n in range(1, 110)} <= ids
    assert len(deep_sky) == 219


def test_reference_positions_match_independent_sources():
    catalog = _catalog()
    deep_sky = {item["id"]: item for item in catalog["deep_sky"]}
    c33 = deep_sky["caldwell:C33"]
    # OpenNGC / SIMBAD NGC 6992: 20:56:19.0 +31:44:36
    assert _separation(c33["ra_deg"], c33["dec_deg"], 314.0792, 31.7433) < 0.01
    assert (c33["designation"], c33["long_designation"], c33["name"]) == (
        "C 33",
        "Caldwell 33",
        "East Veil Nebula",
    )
    assert c33["object_type"] == "supernova_remnant"
    # SIMBAD Sirius J2000: 06h45m08.917s -16d42m58.02s
    sirius = next(row for row in catalog["stars"] if row[0] == 32349)
    assert _separation(sirius[1], sirius[2], 101.28715, -16.71612) < 0.001
    # C36/C38 are absent from d3-celestial; they must still resolve (SIMBAD-checked)
    assert _separation(deep_sky["caldwell:C38"]["ra_deg"], deep_sky["caldwell:C38"]["dec_deg"],
                       189.0867, 25.9874) < 0.01
    assert deep_sky["caldwell:C99"]["ra_deg"] == 192.5


def test_star_labels_and_culture_aliases():
    names = _catalog()["star_names"]
    assert names["102488"]["label"] == "Epsilon Cygni"
    assert names["102488"]["name"] == "Aljanah"
    assert "Marfak-East" in names["5542"]["aliases"]
    assert names["5542"]["label"] == "Theta Cassiopeiae"
    assert names["20535"]["label"] == "Upsilon³ Eridani"
    assert names["22449"]["label"] == "Pi³ Orionis"


def test_every_input_is_pinned_and_licensed():
    lock = json.loads((SKY_DIR / "sources.lock.json").read_text(encoding="utf-8"))
    for item in lock["inputs"]:
        assert len(item["sha256"]) == 64
        assert item["license"] in {"BSD-3-Clause", "CC-BY-SA-4.0"}
        assert item["url"].startswith("https://")
    for name in ("LICENSE.d3-celestial", "CC-BY-SA-4.0.txt", "ATTRIBUTION.md"):
        assert (SKY_DIR / name).is_file()
