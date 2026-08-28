import pytest

from integration.htr_context_consumer import HTRContextError, consume_htr_context


def row():
    return {
        "candidate_id": "htr_seed",
        "source_observation_id": "toponym:calle_luchetti_villalba",
        "hydro_entity_id": "hydro-name-family:antonio_lucchetti",
        "state": "CONTEXT_SUPPORTED",
        "identity_state": "DISTINCT_ENTITIES",
        "downstream_semantics": "CONTEXT_ONLY_NOT_IDENTITY",
        "relation_type": "ORTHOGRAPHIC_VARIANT",
        "evidence": [],
    }


def test_context_never_promotes_mission_or_identity():
    out = consume_htr_context([row()])[0]
    assert out["context_only"] is True
    assert out["can_influence_mission_classification"] is False
    assert out["can_establish_facility_identity"] is False
    assert out["can_establish_connectivity"] is False


def test_discovery_only_row_is_rejected():
    r = row(); r["state"] = "CANDIDATE_NOT_IDENTITY"
    with pytest.raises(HTRContextError):
        consume_htr_context([r])


def test_identity_relation_is_rejected():
    r = row(); r["relation_type"] = "SAME_AS"
    with pytest.raises(HTRContextError):
        consume_htr_context([r])
