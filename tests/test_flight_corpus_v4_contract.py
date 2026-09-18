import json
from pathlib import Path

CFG = Path(__file__).parents[1] / "config" / "flight_corpus_v4.json"

def load():
    return json.loads(CFG.read_text(encoding="utf-8"))

def test_pair_denominator_closes():
    d = load()["denominators"]
    n = d["trajectory_eligible"]
    assert d["unordered_pair_denominator"] == n * (n - 1) // 2
    assert n == d["nonempty_logical_records"] - d["single_point_exclusions"]

def test_trajectory_gate_is_explicit():
    assert load()["trajectory_eligibility"]["minimum_valid_spatial_observations"] >= 2

def test_identity_dimensions_remain_separate():
    dims = load()["identity_dimensions"]
    assert len(dims) == len(set(dims))
    for required in ("AIRFRAME", "CALLSIGN", "OWNER", "OPERATOR", "MISSION"):
        assert required in dims

def test_non_inference_gates_fail_closed():
    gates = load()["interpretation_gates"]
    assert gates
    assert all(value is False for value in gates.values())

def test_candidate_does_not_promote_mission():
    candidate = load()["promoted_candidates"][0]
    assert candidate["classification"] == "REPEATED_AIRBORNE_CO_ROUTE_CANDIDATE"
    assert candidate["mission"] == "UNKNOWN"
    assert candidate["coordination"] == "UNKNOWN"

def test_blockers_preserved():
    blocked = set(load()["blocked"])
    assert "N2JJ_RAW_SOURCE_LINEAGE" in blocked
    assert "COMPLETE_ISLANDWIDE_ELECTRICAL_GRID_DENOMINATOR" in blocked
    assert "HBAL_CROSS_IDENTIFIER_IDENTITY" in blocked
