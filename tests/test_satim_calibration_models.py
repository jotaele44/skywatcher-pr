from fr24.calibration.models import LayerCalibrationResult, derive_overall_status
from fr24.calibration.readiness_adapter import satim_report_to_legacy_calibration


def test_layer_result_rejects_unknown_status():
    try:
        LayerCalibrationResult(layer="Lx", status="UNKNOWN_STATUS")
    except ValueError as exc:
        assert "invalid SATIM layer status" in str(exc)
    else:
        raise AssertionError("expected unknown status to raise")


def test_derive_overall_status_l5_missing_is_partial():
    layers = {
        "L1_ui_segmenter": {"status": "READY"},
        "L2_route_extractor": {"status": "READY"},
        "L3_vision_ocr": {"status": "READY"},
        "L4_aircraft_intelligence": {"status": "READY"},
        "L5_tile_seam_shadow": {"status": "MISSING"},
    }
    assert derive_overall_status(layers) == "PARTIAL"


def test_satim_report_to_legacy_calibration_warns_on_partial_layer():
    legacy = satim_report_to_legacy_calibration({
        "schema_version": "satim.calibration.v1",
        "overall_status": "PARTIAL",
        "layers": {"L4_aircraft_intelligence": {"status": "PARTIAL", "metrics": {"record_count": 3}}},
    })
    assert legacy["status"] == "WARN"
    assert legacy["calibration_flags"][0]["metric"] == "L4_aircraft_intelligence"
    assert legacy["candidate_count"] == 3
