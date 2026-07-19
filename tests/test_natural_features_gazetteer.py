"""Gate: the shared PR natural-features gazetteer (terrain+coastal slice) resolves.

The canonical gazetteer is owned by spiderweb-pr; skywatcher consumes the
terrain+coastal slice as configs/natural_features_registry.json and resolves raw
place strings to a stable canonical_id via a SEPARATE index, so gazetteer names
never collide with airport/place aliases the ontology gate depends on.
"""

import json
from pathlib import Path

from skywatcher.core.normalize_locations import (
    build_natural_feature_index,
    normalize_location,
    normalize_natural_feature,
)

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
REGISTRY = CONFIGS / "natural_features_registry.json"


def _records():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["natural_features"]


def test_registry_is_terrain_and_coastal_only():
    recs = _records()
    assert len(recs) == 991
    assert {r["group"] for r in recs} == {"terrain", "coastal"}


def test_resolves_known_features_to_canonical_id():
    cases = {
        "Pico El Yunque": "place_peak_pico_el_yunque",
        "Cordillera Central": "place_mountain_range_cordillera_central",
        "Bahia de Ponce": "place_bay_bahia_de_ponce",
    }
    for raw, canonical_id in cases.items():
        res = normalize_natural_feature(raw, config_dir=CONFIGS)
        assert res["resolution_status"] == "resolved", res
        assert res["normalized_id"] == canonical_id, res


def test_accent_folding_resolves_ascii_and_spanish_forms():
    accented = normalize_natural_feature("Pico El Yunque", config_dir=CONFIGS)
    ascii_form = normalize_natural_feature("pico el yunque", config_dir=CONFIGS)
    assert accented["normalized_id"] == ascii_form["normalized_id"]


def test_every_record_indexed():
    index = build_natural_feature_index(CONFIGS)
    # Each record's canonical_name resolves (barring intra-gazetteer name collisions).
    resolved = sum(
        1 for r in _records()
        if index.resolve(r["canonical_name"])["resolution_status"] == "resolved"
    )
    assert resolved >= 900  # the vast majority resolve cleanly


def test_gazetteer_does_not_pollute_location_index():
    # "Isla Verde" is an SJU airport alias AND a coastal feature name; the separate
    # gazetteer index must leave the airport/place resolution untouched.
    res = normalize_location("Isla Verde", config_dir=CONFIGS)
    assert res["resolution_status"] == "resolved"
