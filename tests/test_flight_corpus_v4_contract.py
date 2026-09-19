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


def test_v4_recurrence_verifies_materialized_bytes():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    client = TestClient(app)
    route = client.get("/api/flight-corpus/v4/route-family-recurrence").json()
    airport = client.get("/api/flight-corpus/v4/airport-edge-recurrence").json()
    assert route["availability"] == "SOURCE_BYTES_AVAILABLE"
    assert airport["availability"] == "SOURCE_BYTES_AVAILABLE"
    assert route["row_count"] == 123
    assert airport["row_count"] == 233
    assert len(route["rows"]) == 123
    assert len(airport["rows"]) == 233
    assert route["member"]["sha256"] == "1938831c7c532fadd7ddea8730a39fc69738faa4a32ba54f7bfa86a92fad3b70"
    assert airport["member"]["sha256"] == "60d581529a40e6a78c4f8858978b670a94ac174f446fc481c98e8928405d940d"
    assert route["interpretation"]["recurrence_is_mission"] is False
    assert route["interpretation"]["derived_is_raw"] is False


def test_v4_recurrence_filters_conserve_rows():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    client = TestClient(app)
    all_rows = client.get("/api/flight-corpus/v4/route-family-recurrence").json()["rows"]
    sep = client.get("/api/flight-corpus/v4/route-family-recurrence?month=2025-09").json()["rows"]
    family = client.get("/api/flight-corpus/v4/route-family-recurrence?family=1").json()["rows"]
    assert sep and all(row["utc_month"] == "2025-09" for row in sep)
    assert family and all(str(row["consensus_family_id"]) == "1" for row in family)
    assert len(sep) <= len(all_rows)
    assert len(family) <= len(all_rows)


def test_v4_airport_filters_preserve_unknown_semantics():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    client = TestClient(app)
    all_result = client.get("/api/flight-corpus/v4/airport-edge-recurrence").json()
    sig = client.get("/api/flight-corpus/v4/airport-edge-recurrence?departure=SIG").json()
    sep = client.get("/api/flight-corpus/v4/airport-edge-recurrence?month=2025-09").json()
    assert all_result["row_count"] == 233
    assert sig["rows"] and all(row["departure"] == "SIG" for row in sig["rows"])
    assert sep["rows"] and all(row["utc_month"] == "2025-09" for row in sep["rows"])
    assert sig["row_count"] <= all_result["row_count"]
    assert sep["row_count"] <= all_result["row_count"]
    assert all_result["interpretation"]["blank_airport_is_no_airport"] is False


def test_v4_family_provenance_preserves_superseded_discovery():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    body = TestClient(app).get("/api/flight-corpus/v4/family-provenance").json()
    assert body["state"] == "SUPERSEDED_BOUNDARIES"
    assert body["discovery_is_identity"] is False
    assert body["subfamily_is_mission"] is False
    assert [row["v3_family"] for row in body["superseded_families"]] == [1, 2, 3, 4]
    assert body["split_member"]["sha256"] == "b85b3d5c326f150a1d2f851d517b4c7ede3d26f04426ac80470b5c08778a3a88"
    assert body["summary_member"]["sha256"] == "9a0887d4a69a07cebf31b5161f300b18221a042a73034308624aafc227bce209"


def test_v4_family_split_summary_exact_bytes_and_semantics():
    from fastapi.testclient import TestClient

    from server.backend.main import app

    body = TestClient(app).get("/api/flight-corpus/v4/family-split-summary").json()
    assert body["availability"] == "SOURCE_BYTES_AVAILABLE"
    assert body["row_count"] == 46
    assert body["member"]["sha256"] == "9a0887d4a69a07cebf31b5161f300b18221a042a73034308624aafc227bce209"
    assert body["rows"][0]["consensus_family_id"] == "-1"
    assert body["rows"][0]["tracks"] == "359"
    assert body["interpretation"]["minus_one_is_canonical_family"] is False
    assert body["interpretation"]["family_is_identity"] is False
    assert body["interpretation"]["subfamily_is_mission"] is False
