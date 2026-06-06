"""Tests for PRIIReadinessEngine: contract, verdict, blocker/warning routing."""

import json
from pathlib import Path

import pytest

from prii_readiness_engine import (
    READINESS_STATUS_DEGRADED,
    READINESS_STATUS_NOT_READY,
    READINESS_STATUS_READY,
    REQUIRED_REPORT_KEYS,
    PRIIReadinessEngine,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _passing_integration_report() -> dict:
    return {
        "generated_at": "2024-03-15T08:00:00Z",
        "overall_status": "PASS",
        "gates": {
            "schema_validation":      {"status": "PASS", "records_validated": 9, "invalid": 0},
            "coordinate_coverage":    {"status": "PASS", "pct_with_coords": 1.0, "threshold": 0.70},
            "ocr_confidence_gate":    {"status": "PASS", "avg_confidence": 0.85, "threshold": 0.50},
            "evidence_chain_coverage":{"status": "PASS", "pct_with_screenshot": 1.0, "threshold": 0.50},
            "export_completeness":    {"status": "PASS", "files_generated": 9, "missing": []},
            "temporal_integrity":     {"status": "PASS", "violations": 0},
        },
    }


def _passing_calibration_report(export_dir: Path) -> dict:
    return {
        "generated_at": "2024-03-15T08:00:00Z",
        "export_dir": str(export_dir),
        "baseline_mode": "operational",
        "status": "PASS",
        "missing_inputs": [],
        "candidate_count": 100,
        "tier_distribution": {"T4": 70, "T3": 20, "T2": 7, "T1": 3},
        "calibration_flags": [],
    }


def _write(export_dir: Path, filename: str, data: dict) -> None:
    (export_dir / filename).write_text(json.dumps(data), encoding="utf-8")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_ready_with_both_inputs_passing(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_READY
    assert report["blockers"] == []
    assert report["warnings"] == []


def test_not_ready_when_prii_gate_fails(tmp_path):
    integration = _passing_integration_report()
    integration["overall_status"] = "FAIL"
    integration["gates"]["coordinate_coverage"]["status"] = "FAIL"
    integration["gates"]["coordinate_coverage"]["pct_with_coords"] = 0.45
    _write(tmp_path, "integration_report.json", integration)
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))

    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_NOT_READY
    assert len(report["blockers"]) >= 1
    blocker_sources = [b["source"] for b in report["blockers"]]
    assert "prii_gate" in blocker_sources
    gate_names = [b["gate"] for b in report["blockers"] if b["source"] == "prii_gate"]
    assert "coordinate_coverage" in gate_names


def test_not_ready_when_calibration_fails(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["status"] = "FAIL"
    cal["baseline_mode"] = "operational"
    cal["calibration_flags"] = [
        {"metric": "pct_T4", "value": 0.85, "expected_max": 0.70,
         "action": "investigate tier thresholds"},
    ]
    _write(tmp_path, "calibration_report.json", cal)

    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_NOT_READY
    cal_blockers = [b for b in report["blockers"] if b["source"] == "calibration"]
    assert len(cal_blockers) == 1
    assert cal_blockers[0]["flag"] == "pct_T4"


def test_degraded_when_calibration_warns(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["status"] = "WARN"
    cal["baseline_mode"] = "fixture"
    cal["candidate_count"] = 6
    cal["calibration_flags"] = [
        {"metric": "pct_hydro_yes", "value": 0.02, "expected_min": 0.05,
         "action": "expand HYDRO_LOCATIONS"},
    ]
    _write(tmp_path, "calibration_report.json", cal)

    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_DEGRADED
    assert report["blockers"] == []
    cal_warnings = [w for w in report["warnings"] if w["source"] == "calibration"]
    assert len(cal_warnings) == 1
    assert "WARN" in cal_warnings[0]["detail"]


def test_degraded_when_integration_report_missing(tmp_path):
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    # No integration_report.json

    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_DEGRADED
    assert report["blockers"] == []
    prii_warnings = [w for w in report["warnings"] if w["source"] == "prii_report"]
    assert len(prii_warnings) == 1
    assert "integration_report.json" in report["missing_inputs"]


def test_report_written_to_disk(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    PRIIReadinessEngine(str(tmp_path)).assess()
    report_path = tmp_path / "prii_readiness_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["readiness_status"] == READINESS_STATUS_READY


def test_report_has_required_keys(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    for key in REQUIRED_REPORT_KEYS:
        assert key in report, f"Required key missing from readiness report: {key}"


def test_missing_both_inputs_does_not_crash(tmp_path):
    # Empty export dir — engine should produce DEGRADED, not raise
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["readiness_status"] == READINESS_STATUS_DEGRADED
    assert isinstance(report["blockers"], list)
    assert isinstance(report["warnings"], list)
    assert len(report["missing_inputs"]) == 2


# ── Phase 8: Dashboard & Output Layer ────────────────────────────────────────

def test_get_gate_status_text_returns_string(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    gate = {"status": "PASS", "pct_with_coords": 1.0, "threshold": 0.70}
    text = engine.get_gate_status_text("coordinate_coverage", gate)
    assert isinstance(text, str)
    assert "coordinate_coverage" in text


def test_get_gate_status_text_pass_gate(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    gate = {"status": "PASS", "invalid": 0}
    text = engine.get_gate_status_text("schema_validation", gate)
    assert "PASS" in text


def test_get_gate_status_text_fail_gate(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    gate = {"status": "FAIL", "avg_confidence": 0.3, "threshold": 0.5}
    text = engine.get_gate_status_text("ocr_confidence_gate", gate)
    assert "FAIL" in text
    assert "0.3" in text


def test_get_gate_status_text_unknown_gate(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    text = engine.get_gate_status_text("some_custom_gate", {"status": "PASS"})
    assert "some_custom_gate" in text
    assert "PASS" in text


def test_assess_satellite_manifests_empty_dir(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    result = engine.assess_satellite_manifests(str(tmp_path))
    assert result["status"] in ("WARN", "MISSING")


def test_assess_satellite_manifests_missing_dir(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    result = engine.assess_satellite_manifests(str(tmp_path / "nonexistent"))
    assert result["status"] == "MISSING"


def test_assess_satellite_manifests_with_manifest(tmp_path):
    (tmp_path / "sat_manifest.json").write_text("{}", encoding="utf-8")
    engine = PRIIReadinessEngine(str(tmp_path))
    result = engine.assess_satellite_manifests(str(tmp_path))
    assert result["status"] == "PASS"
    assert "1" in result["message"]


def test_to_schema_report_has_required_keys(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    schema_report = engine.to_schema_report(assess_result)
    for key in ("generated_at", "status", "gates", "warnings", "errors", "notes"):
        assert key in schema_report, f"Missing key: {key}"


def test_to_schema_report_status_is_ready(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    schema_report = engine.to_schema_report(assess_result)
    assert schema_report["status"] == "READY"


def test_to_schema_report_includes_satellite_gate(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    schema_report = engine.to_schema_report(assess_result)
    assert "satellite_manifests" in schema_report["gates"]
    assert "status" in schema_report["gates"]["satellite_manifests"]


def test_to_schema_report_calibration_fail(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["status"] = "FAIL"
    cal["calibration_flags"] = [
        {"metric": "pct_T4", "value": 0.90, "expected_max": 0.70,
         "action": "investigate tier thresholds"},
    ]
    _write(tmp_path, "calibration_report.json", cal)
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    schema_report = engine.to_schema_report(assess_result)
    assert schema_report["gates"]["calibration"]["status"] == "FAIL"
    assert "pct_T4" in schema_report["gates"]["calibration"]["message"]


def test_format_readiness_text_contains_status(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    report = engine.assess()
    text = engine.format_readiness_text(report)
    assert isinstance(text, str)
    assert "READY" in text


def test_format_readiness_text_contains_blocker(tmp_path):
    integration = _passing_integration_report()
    integration["gates"]["schema_validation"]["status"] = "FAIL"
    integration["gates"]["schema_validation"]["invalid"] = 3
    _write(tmp_path, "integration_report.json", integration)
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    report = engine.assess()
    text = engine.format_readiness_text(report)
    assert "Blockers" in text


def test_export_dashboard_json_creates_file(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    out_path = tmp_path / "dashboard.json"
    engine.export_dashboard_json(assess_result, str(out_path))
    assert out_path.exists()


def test_export_dashboard_json_valid_schema_format(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assess_result = engine.assess()
    out_path = tmp_path / "dashboard.json"
    engine.export_dashboard_json(assess_result, str(out_path))
    data = json.loads(out_path.read_text())
    assert "status" in data
    assert "gates" in data
    assert data["status"] in ("READY", "NOT_READY", "DEGRADED")


# ── Phase 10: Observability ───────────────────────────────────────────────────

def test_health_check_healthy(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    hc = engine.health_check()
    assert hc["status"] == "healthy"
    assert hc["checks"]["integration_report.json"] == "ok"
    assert hc["checks"]["calibration_report.json"] == "ok"


def test_health_check_degraded_one_missing(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    engine = PRIIReadinessEngine(str(tmp_path))
    hc = engine.health_check()
    assert hc["status"] == "degraded"
    assert hc["checks"]["calibration_report.json"] == "missing"


def test_health_check_unhealthy_both_missing(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    hc = engine.health_check()
    assert hc["status"] == "unhealthy"


def test_health_check_has_export_dir(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    hc = engine.health_check()
    assert "export_dir" in hc


# ── Task 34: calibration_ready field ─────────────────────────────────────────

def test_calibration_ready_true_when_operational_pass(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["calibration_ready"] is True


def test_calibration_ready_false_when_fixture_mode(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["baseline_mode"] = "fixture"
    _write(tmp_path, "calibration_report.json", cal)
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["calibration_ready"] is False


def test_calibration_ready_false_when_no_calibration_report(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["calibration_ready"] is False


def test_calibration_ready_false_when_calibration_fail(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["status"] = "FAIL"
    _write(tmp_path, "calibration_report.json", cal)
    report = PRIIReadinessEngine(str(tmp_path)).assess()
    assert report["calibration_ready"] is False


# ── Task 200: PRODUCTION_READY property ───────────────────────────────────────

def test_production_ready_true_when_all_pass(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    _write(tmp_path, "calibration_report.json", _passing_calibration_report(tmp_path))
    engine = PRIIReadinessEngine(str(tmp_path))
    assert engine.PRODUCTION_READY is True


def test_production_ready_false_when_calibration_fixture(tmp_path):
    _write(tmp_path, "integration_report.json", _passing_integration_report())
    cal = _passing_calibration_report(tmp_path)
    cal["baseline_mode"] = "fixture"
    _write(tmp_path, "calibration_report.json", cal)
    engine = PRIIReadinessEngine(str(tmp_path))
    assert engine.PRODUCTION_READY is False


def test_production_ready_false_when_no_files(tmp_path):
    engine = PRIIReadinessEngine(str(tmp_path))
    assert engine.PRODUCTION_READY is False
