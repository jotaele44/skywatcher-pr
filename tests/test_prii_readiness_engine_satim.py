import json

from prii_readiness_engine import PRIIReadinessEngine, READINESS_STATUS_READY_FOR_OPS


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_prii_readiness_engine_accepts_satim_v1_calibration_report(tmp_path):
    write_json(tmp_path / "integration_report.json", {"overall_status": "PASS", "gates": {}})
    write_json(
        tmp_path / "calibration_report.json",
        {
            "schema_version": "satim.calibration.v1",
            "overall_status": "READY_FOR_BATCH_ANALYSIS",
            "layers": {
                "L1_ui_segmenter": {"status": "READY", "metrics": {"image_count": 2}},
                "L2_route_extractor": {"status": "READY", "metrics": {"image_count": 2}},
                "L3_vision_ocr": {"status": "READY", "metrics": {"record_count": 2}},
                "L4_aircraft_intelligence": {"status": "READY", "metrics": {"record_count": 2}},
                "L5_tile_seam_shadow": {"status": "READY", "metrics": {"candidate_count": 1}},
            },
        },
    )

    report = PRIIReadinessEngine(str(tmp_path)).assess()

    assert report["readiness_status"] == "READY"
    assert report["final_status"] == READINESS_STATUS_READY_FOR_OPS
    assert report["calibration_ready"] is True
    assert report["gate_summary"]["calibration_status"] == "PASS"
    assert report["gate_summary"]["baseline_mode"] == "operational"
    assert report["gate_summary"]["candidate_count"] == 9


def test_prii_readiness_engine_marks_partial_satim_report_degraded(tmp_path):
    write_json(tmp_path / "integration_report.json", {"overall_status": "PASS", "gates": {}})
    write_json(
        tmp_path / "calibration_report.json",
        {
            "schema_version": "satim.calibration.v1",
            "overall_status": "PARTIAL",
            "layers": {
                "L1_ui_segmenter": {"status": "READY", "metrics": {"image_count": 1}},
                "L5_tile_seam_shadow": {"status": "MISSING", "metrics": {}},
            },
        },
    )

    report = PRIIReadinessEngine(str(tmp_path)).assess()

    assert report["readiness_status"] == "DEGRADED"
    assert report["final_status"] == "DEGRADED"
    assert report["calibration_ready"] is False
    assert report["gate_summary"]["calibration_status"] == "WARN"
    assert report["gate_summary"]["baseline_mode"] == "calibration"
    assert report["warnings"]
