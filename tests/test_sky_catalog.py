"""Sky Target Finder catalog loading, search ranking and filter hints."""

from __future__ import annotations

from pathlib import Path

from skywatcher.core.sky.catalog import load_catalog, normalize_text, search_catalog
from skywatcher.core.sky.filters import filter_hint

SKY_DIR = Path(__file__).resolve().parents[1] / "data" / "reference" / "sky"
ALL = frozenset({"star", "messier", "caldwell"})


def test_catalog_indexes_every_object():
    catalog = load_catalog(SKY_DIR)
    kinds = [item.kind for item in catalog.objects]
    assert kinds.count("messier") == 110
    assert kinds.count("caldwell") == 109
    assert kinds.count("star") == len(catalog.star_labels) > 2900
    assert len(catalog.stars) == len(catalog.star_vectors) == 5044
    assert len(catalog.deep_stars) == len(catalog.deep_star_vectors) > 20000


def test_search_east_finds_the_targets_from_the_recording():
    results = search_catalog(load_catalog(SKY_DIR), "East", ALL)
    by_id = {item.id: (item, match) for item, match in results}
    veil, match = by_id["caldwell:C33"]
    assert veil.display == "C 33 (East Veil Nebula)"
    assert (match.field, match.text) == ("name", "East Veil Nebula")
    marfak, match = by_id["star:hip:5542"]
    assert marfak.display == "Theta Cassiopeiae (Marfak)"
    assert match.text == "Marfak-East"
    assert results[0][0].id == "caldwell:C33"  # prefix match outranks the alias substring


def test_search_ranks_exact_name_matches_before_aliases():
    results = search_catalog(load_catalog(SKY_DIR), "Marfak", ALL)
    first_two = {item.id for item, _ in results[:2]}
    assert first_two == {"star:hip:5542", "star:hip:5336"}  # proper name "Marfak"
    assert "star:hip:15863" in {item.id for item, _ in results}  # Mirfak, alias only


def test_search_andromeda_puts_m31_first_and_respects_kinds():
    catalog = load_catalog(SKY_DIR)
    assert search_catalog(catalog, "andromeda", ALL)[0][0].id == "messier:M31"
    stars_only = search_catalog(catalog, "andromeda", frozenset({"star"}))
    assert stars_only and all(item.kind == "star" for item, _ in stars_only)
    assert search_catalog(catalog, "", ALL) == []


def test_hip_queries_resolve_any_catalog_star():
    catalog = load_catalog(SKY_DIR)
    sirius = search_catalog(catalog, "HIP 32349", ALL)[0][0]
    assert sirius.id == "star:hip:32349" and sirius.name == "Sirius"
    unnamed = catalog.get("star:hip:57439")  # in the base layer, no name or designation
    assert unnamed is not None and unnamed.designation == "HIP 57439"
    assert unnamed.name is None and unnamed.kind == "star"
    assert catalog.get("caldwell:C200") is None


def test_text_normalization_is_case_and_accent_insensitive():
    assert normalize_text("  Boötes ") == "bootes"
    assert normalize_text("East  Veil") == "east veil"


def test_filter_hints():
    assert filter_hint("supernova_remnant") == {"label": "Duo-Band", "basis": "heuristic"}
    assert filter_hint("emission_nebula")["label"] == "Duo-Band"
    assert filter_hint("galaxy")["label"] == "Broadband"
    assert filter_hint("star") is None and filter_hint(None) is None
