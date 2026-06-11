"""Offline tests for fr24.zone_label_harvest (no OCR / no images).

Exercises the registry loader, frame classifier, endpoint extraction, and code
resolution against the PR Landing Zones + Military GeoPackages.
"""
from __future__ import annotations

import pytest

from fr24 import zone_label_harvest as zlh


@pytest.fixture(scope="module")
def reg():
    return zlh.load_registry()


def test_registry_loads_known_airports(reg):
    names = reg["names"]
    # PR registry (ICAO + IATA) and a static off-PR extra
    assert names.get("SJU", "").startswith("Luis Mu")
    assert names.get("TJSJ") == names.get("SJU")
    assert "BQN" in names and "PSE" in names
    assert names.get("MIA", "").startswith("Miami")
    # verification class flows through
    assert reg["vclass"].get("SJU") == "Active-Verified"
    assert reg["vclass"].get("MIA") == "ExternalStatic"
    # places carry coordinates for later geo-nearest resolution
    assert any(p.get("lat") for p in reg["places"])


def test_classify_frame():
    fr24_text = "BGI LAL BAROMETRIC ALT. 44,975 ft GROUND SPEED 497 mph Departed"
    earth_text = "Bunker de la Interamericana Buchanan Golf Club Almacen"
    assert zlh.classify_frame(fr24_text) == "fr24"
    assert zlh.classify_frame(earth_text) == "earth_or_other"


def test_extract_endpoints_gazetteer(reg):
    names = reg["names"]
    text = "BGI LAL\nBRIDGETOWN LAKELAND 44,975 ft\nDeparted 06:11 ago Arriving in 01:18"
    o, d, status, source = zlh._extract_endpoints(text, names)
    assert (o, d) == ("BGI", "LAL")
    assert source == "gazetteer"
    assert status == "departed"


def test_extract_endpoints_not_available(reg):
    names = reg["names"]
    text = "N/A N/A NOT AVAILABLE NOT AVAILABLE BAROMETRIC ALT. 44,050 ft"
    o, d, status, source = zlh._extract_endpoints(text, names)
    assert status == "not_available"
    assert source in ("none", "fallback")  # never a confident gazetteer hit


def test_resolve_code(reg):
    names = reg["names"]
    assert zlh.resolve_code("SJU", names).startswith("Luis Mu")
    assert zlh.resolve_code("ZZZ", names) == ""
    assert zlh.resolve_code("", names) == ""


def test_gnis_layer_loaded(reg):
    assert len(reg["gnis"]) > 5000
    assert len(reg["gnis_index"]) > 4000


def test_resolve_place_name_accent_folding(reg):
    # OCR'd labels rarely carry diacritics; matching must be accent-insensitive
    assert "Mayag" in (zlh.resolve_place_name("Mayaguez", reg) or {}).get("name", "")
    assert "Aguadilla" in (zlh.resolve_place_name("Aguadilla", reg) or {}).get("name", "")
    assert zlh.resolve_place_name("NotARealTown_xyz", reg) is None


def test_nearest_place_prefers_landing_zone(reg):
    # SJU airport coordinates resolve to the airport, not a nearby town
    p = zlh.nearest_place(18.4394, -66.0012, reg, max_nm=4)
    assert p is not None and p["layer"] == "landing_zone"
    assert "Luis Mu" in p["name"]
    # open ocean resolves to nothing within range
    assert zlh.nearest_place(19.6, -66.0, reg, max_nm=3) is None


def test_haversine_sane():
    # ~ SJU to BQN is roughly 60-70 nm
    d = zlh.haversine_nm(18.4394, -66.0012, 18.4949, -67.1294)
    assert 55 < d < 75


def test_scan_place_names(reg):
    multi = zlh.scan_place_names("Aguadilla Mayaguez Ponce San Juan", reg)
    assert len(multi) >= 3 and any("Ponce" in n for n in multi)
    single = zlh.scan_place_names("only Carolina visible", reg)
    assert single == ["Carolina Municipio"]
    assert zlh.scan_place_names("xyzzy qwerty", reg) == []


def test_row_schema_has_suggestion_columns():
    row = zlh._row("x.png", "fr24", "unknown", "", "", "", "", "", "src",
                   "REVIEW", "reason", 10, "text",
                   suggested_name="Carolina Municipio", nearby_places="A; B")
    assert set(zlh.FIELDNAMES) <= set(row)
    assert row["suggested_name"] == "Carolina Municipio"
    assert row["nearby_places"] == "A; B"
