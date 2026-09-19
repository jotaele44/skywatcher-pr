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


def test_v4_status_api_preserves_unknown_and_blockers():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    response = TestClient(app).get("/api/flight-corpus/v4/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROVISIONAL"
    assert "N2JJ_RAW_SOURCE_LINEAGE" in body["blocked"]
    candidate = body["promoted_candidates"][0]
    assert candidate["mission"] == "UNKNOWN"
    assert candidate["coordination"] == "UNKNOWN"
    assert body["artifact_bound"] is True
    assert body["artifact"]["sha256"] == "eebbf64baced4a2f7e325627a64ab75b01b340ef1ac9b07a2097b91ec95b90f8"


def test_v4_artifact_member_denominator():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    response = TestClient(app).get("/api/flight-corpus/v4/artifact-members")
    assert response.status_code == 200
    members = response.json()
    assert len(members) == 13
    assert len({row["path"] for row in members}) == 13


def test_v4_deep_interface_preserves_provenance_and_noninference():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    response = TestClient(app).get("/api/flight-corpus/v4/deep-interface")
    assert response.status_code == 200
    body = response.json()
    assert len(body["members"]) == 13
    assert body["exclusion_state"]["single_point_nontrajectory_records"] == 11
    assert body["contradiction_state"]["identity_source_contradictions_v2"] == 47
    assert body["temporal_recurrence"]["availability"] == "EXTERNAL_ARTIFACT_BOUND"
    assert body["temporal_recurrence"]["route_family_member"]["sha256"] == "1938831c7c532fadd7ddea8730a39fc69738faa4a32ba54f7bfa86a92fad3b70"
    assert body["interpretation"]["route_recurrence_is_mission"] is False
    assert body["interpretation"]["candidate_is_coordination"] is False


def test_v4_recurrence_fails_closed_without_local_bytes():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    client = TestClient(app)
    route = client.get("/api/flight-corpus/v4/route-family-recurrence").json()
    airport = client.get("/api/flight-corpus/v4/airport-edge-recurrence").json()
    assert route["availability"] == "EXTERNAL_ARTIFACT_BOUND"
    assert airport["availability"] == "EXTERNAL_ARTIFACT_BOUND"
    assert route["rows"] == [] and route["row_count"] == 0
    assert airport["rows"] == [] and airport["row_count"] == 0
    assert route["member"]["sha256"] == "1938831c7c532fadd7ddea8730a39fc69738faa4a32ba54f7bfa86a92fad3b70"
    assert airport["member"]["sha256"] == "60d581529a40e6a78c4f8858978b670a94ac174f446fc481c98e8928405d940d"
    assert route["interpretation"]["recurrence_is_mission"] is False
    assert route["interpretation"]["derived_is_raw"] is False
