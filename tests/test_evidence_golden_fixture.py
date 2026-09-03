from __future__ import annotations

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "evidence_router"
    / "N5854Z_TRES_MONJITAS_UTILITY_CORRIDOR.json"
)


def _load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_n5854z_fixture_denominator_and_hash_uniqueness() -> None:
    fixture = _load()
    source = fixture["source_manifest"]
    assert isinstance(source, dict)
    images = source["images"]
    assert isinstance(images, list)
    assert source["count"] == 9 == len(images)
    hashes = [row["sha256"] for row in images]
    assert len(hashes) == len(set(hashes))
    assert all(len(value) == 64 for value in hashes)


def test_n5854z_fixture_forbids_known_false_promotions() -> None:
    fixture = _load()
    prohibited = set(fixture["prohibited_promotions"])
    assert {
        "0_FT->ON_GROUND",
        "0_MPH->LANDED",
        "MAP_LABEL->TARGET",
        "NEAREST_POI->TARGET",
        "OWNER->OPERATOR",
        "OPERATOR->MISSION",
        "RENDERED_TRAIL->RAW_TRAJECTORY",
        "CORRIDOR_ALIGNMENT->EXACT_MISSION",
    } <= prohibited


def test_n5854z_fixture_requires_full_downstream_route() -> None:
    fixture = _load()
    assert set(fixture["expected_router_skills"]) == {
        "RLSM",
        "FPIM",
        "CORRIM",
        "SATIM",
        "TIMELINE",
        "PATTERN",
    }
    states = fixture["expected_certification_states"]
    assert isinstance(states, dict)
    assert states["LANDING"] == "UNRESOLVED"
    assert states["FACILITY_TARGET"] == "CANDIDATE_NOT_IDENTITY"
    assert states["ANALYTICAL_CERTIFICATION"] == "OPEN"
