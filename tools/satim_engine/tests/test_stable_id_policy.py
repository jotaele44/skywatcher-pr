from satim_engine.graph import stable_id


def test_stable_id_is_deterministic():
    assert stable_id("x", "a", 1) == stable_id("x", "a", 1)
    assert stable_id("x", "a", 1) != stable_id("x", "a", 2)
