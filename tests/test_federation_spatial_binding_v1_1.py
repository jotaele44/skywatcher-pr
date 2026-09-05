from scripts.federation_spatial_binding_v1_1 import bind_record


def test_track_intersection_cannot_create_identity():
    row = {"faa_lid": "SJU"}
    try:
        bind_record(
            row,
            id_field="faa_lid",
            id_namespace="faa_lid",
            canonical_index={"skywatcher-pr:faa_lid:SJU": ["pr:airport:sju"]},
            evidence_basis=["TRACK_INTERSECTION"],
        )
    except ValueError as exc:
        assert "heuristic-only" in str(exc)
    else:
        raise AssertionError("track intersection must not create identity")


def test_faa_lid_match_is_only_provisional():
    row = {"faa_lid": "sju"}
    result = bind_record(
        row,
        id_field="faa_lid",
        id_namespace="faa_lid",
        canonical_index={"skywatcher-pr:faa_lid:SJU": ["pr:airport:sju"]},
        evidence_basis=["FAA_LID"],
    )
    assert result["cardinality"] == "1:1"
    assert result["identity_state"] == "PROVISIONAL"
    assert result["canonical_ids"] == ["pr:airport:sju"]


def test_no_match_stays_unresolved():
    row = {"faa_lid": "BQN"}
    result = bind_record(
        row,
        id_field="faa_lid",
        id_namespace="faa_lid",
        canonical_index={},
        evidence_basis=["FAA_LID"],
    )
    assert result["cardinality"] == "0:1"
    assert result["identity_state"] == "UNRESOLVED"


def test_multiple_candidates_preserve_one_to_many():
    row = {"icao": "TJSJ"}
    result = bind_record(
        row,
        id_field="icao",
        id_namespace="icao",
        canonical_index={
            "skywatcher-pr:icao:TJSJ": ["pr:airport:sju", "pr:airport:sju-historical"]
        },
        evidence_basis=["ICAO_ID"],
    )
    assert result["cardinality"] == "1:N"
    assert result["identity_state"] == "UNRESOLVED"
