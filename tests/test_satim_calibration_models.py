from fr24.calibration.models import (
    LayerCalibrationResult,
    derive_gap_accounting,
    derive_overall_status,
    merge_layer_reports,
    write_json,
)
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


def test_derive_gap_accounting_marks_missing_l3_blocking():
    layers = {
        "L1_ui_segmenter": {"status": "READY"},
        "L2_route_extractor": {"status": "READY"},
        "L3_vision_ocr": {"status": "MISSING"},
        "L4_aircraft_intelligence": {"status": "PARTIAL"},
        "L5_tile_seam_shadow": {"status": "MISSING"},
    }

    blocking_gaps, recommended_next_actions = derive_gap_accounting(layers)

    assert blocking_gaps == [{
        "layer": "L3_vision_ocr",
        "status": "MISSING",
        "severity": "blocker",
        "detail": "L3_vision_ocr is required for SATIM batch readiness and is not READY.",
    }]
    assert "Resolve L4_aircraft_intelligence status PARTIAL" in recommended_next_actions[0]
    assert "Resolve L5_tile_seam_shadow status MISSING" in recommended_next_actions[1]


def test_merge_layer_reports_populates_blocking_gaps(tmp_path):
    l1 = tmp_path / "l1.json"
    l2 = tmp_path / "l2.json"
    l3 = tmp_path / "l3.json"
    l5 = tmp_path / "l5.json"
    output = tmp_path / "calibration_report.json"

    write_json(l1, LayerCalibrationResult(layer="L1_ui_segmenter", status="READY").to_dict())
    write_json(l2, LayerCalibrationResult(layer="L2_route_extractor", status="READY").to_dict())
    write_json(l3, LayerCalibrationResult(layer="L3_vision_ocr", status="MISSING").to_dict())
    write_json(l5, LayerCalibrationResult(layer="L5_tile_seam_shadow", status="MISSING").to_dict())

    report = merge_layer_reports([l1, l2, l3, l5], output)

    assert report["overall_status"] == "DEGRADED"
    assert report["blocking_gaps"] == [{
        "layer": "L3_vision_ocr",
        "status": "MISSING",
        "severity": "blocker",
        "detail": "L3_vision_ocr is required for SATIM batch readiness and is not READY.",
    }]
    assert report["recommended_next_actions"] == [
        "Resolve L4_aircraft_intelligence status MISSING before production promotion.",
        "Resolve L5_tile_seam_shadow status MISSING before production promotion.",
    ]


def test_satim_report_to_legacy_calibration_warns_on_partial_layer():
    legacy = satim_report_to_legacy_calibration({
        "schema_version": "satim.calibration.v1",
        "overall_status": "PARTIAL",
        "layers": {"L4_aircraft_intelligence": {"status": "PARTIAL", "metrics": {"record_count": 3}}},
    })
    assert legacy["status"] == "WARN"
    assert legacy["calibration_flags"][0]["metric"] == "L4_aircraft_intelligence"
    assert legacy["candidate_count"] == 3
