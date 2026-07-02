from fr24 import satim_engine_core as satim_engine


def test_l2_failure_handler_exists():
    assert hasattr(satim_engine, "degraded_layer")
