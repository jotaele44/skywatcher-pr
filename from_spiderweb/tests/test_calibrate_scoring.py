"""Tests for CalibrationDriver in calibrate_scoring.py."""

import json
from pathlib import Path

import pytest

from readiness.calibrate_scoring import (
    REQUIRED_REPORT_KEYS,
    CalibrationDriver,
    MIN_OPERATIONAL_CANDIDATES,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_geojson(path: Path, features: list) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _write_gap_audit(path: Path, duplicates_removed: int = 0) -> None:
    path.write_text(
        json.dumps({"gaps": {"dedup_gap": {"duplicates_removed": duplicates_removed}}}),
        encoding="utf-8",
    )


def _feature(tier="T4", mbil="MBIL-2", hydro="no", utility="yes", terrain="urban"):
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "evidence_tier": tier,
            "mbil_class": mbil,
            "hydro_overlap": hydro,
            "utility_overlap": utility,
            "terrain_context": terrain,
        },
    }


# ── CalibrationDriver ─────────────────────────────────────────────────────────

def test_empty_dir_has_all_required_report_keys(tmp_path):
    report = CalibrationDriver(str(tmp_path)).run()
    for key in REQUIRED_REPORT_KEYS:
        assert key in report, f"Missing key: {key}"


def test_empty_dir_status_is_pass(tmp_path):
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["status"] == "PASS"


def test_empty_dir_candidate_count_zero(tmp_path):
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["candidate_count"] == 0


def test_empty_dir_reports_both_missing_inputs(tmp_path):
    report = CalibrationDriver(str(tmp_path)).run()
    assert len(report["missing_inputs"]) == 2


def test_report_written_to_disk(tmp_path):
    CalibrationDriver(str(tmp_path)).run()
    assert (tmp_path / "calibration_report.json").exists()


def test_report_json_is_valid(tmp_path):
    CalibrationDriver(str(tmp_path)).run()
    data = json.loads((tmp_path / "calibration_report.json").read_text())
    assert isinstance(data, dict)


def test_fixture_mode_for_small_sample(tmp_path):
    _write_geojson(tmp_path / "spiderweb_overlay_candidates.geojson", [_feature()])
    _write_gap_audit(tmp_path / "spiderweb_gap_audit.json")
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["baseline_mode"] == "fixture"
    assert report["candidate_count"] == 1


def test_tier_distribution_counted_correctly(tmp_path):
    features = [_feature(tier="T4")] * 3 + [_feature(tier="T1")] * 1
    _write_geojson(tmp_path / "spiderweb_overlay_candidates.geojson", features)
    _write_gap_audit(tmp_path / "spiderweb_gap_audit.json")
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["tier_distribution"].get("T4") == 3
    assert report["tier_distribution"].get("T1") == 1


def test_dedup_rate_calculation(tmp_path):
    features = [_feature()] * 10
    _write_geojson(tmp_path / "spiderweb_overlay_candidates.geojson", features)
    _write_gap_audit(tmp_path / "spiderweb_gap_audit.json", duplicates_removed=2)
    report = CalibrationDriver(str(tmp_path)).run()
    # 10 remaining + 2 removed = 12 total → 2/12
    assert report["dedup_rate"] == round(2 / 12, 4)


def test_zero_candidates_dedup_rate_is_zero(tmp_path):
    report = CalibrationDriver(str(tmp_path)).run()
    assert report["dedup_rate"] == 0.0


def test_calibration_flags_sorted_by_metric(tmp_path):
    features = [_feature(hydro="no", utility="no")] * 5
    _write_geojson(tmp_path / "spiderweb_overlay_candidates.geojson", features)
    _write_gap_audit(tmp_path / "spiderweb_gap_audit.json")
    report = CalibrationDriver(str(tmp_path)).run()
    flags = report["calibration_flags"]
    metrics = [f["metric"] for f in flags]
    assert metrics == sorted(metrics)


def test_custom_output_dir(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    out_dir = tmp_path / "out"
    CalibrationDriver(str(export_dir), output_dir=str(out_dir)).run()
    assert (out_dir / "calibration_report.json").exists()


# ── Phase 7: explain_flags ────────────────────────────────────────────────────

def test_explain_flags_no_flags_returns_pass(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_geojson(export_dir / "spiderweb_overlay_candidates.geojson", [_feature()] * 60)
    _write_gap_audit(export_dir / "spiderweb_gap_audit.json")
    report = CalibrationDriver(str(export_dir)).run()
    explanation = CalibrationDriver(str(export_dir)).explain_flags(report)
    assert isinstance(explanation, str)
    if not report["calibration_flags"]:
        assert "PASS" in explanation


def test_explain_flags_with_flags_contains_metric(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    report_with_flags = {
        "status": "FAIL",
        "baseline_mode": "operational",
        "calibration_flags": [
            {"metric": "pct_T4", "value": 0.01, "expected_min": 0.05,
             "action": "Investigate tier scoring"},
        ],
    }
    driver = CalibrationDriver(str(export_dir))
    explanation = driver.explain_flags(report_with_flags)
    assert "pct_T4" in explanation
    assert "FAIL" in explanation


def test_explain_flags_empty_report_returns_pass(tmp_path):
    driver = CalibrationDriver(str(tmp_path))
    result = driver.explain_flags({"calibration_flags": []})
    assert "PASS" in result


# ── Phase 10: Observability ───────────────────────────────────────────────────

def _run_report(tmp_path, n_features, tier="T4", hydro="no", utility="yes"):
    features = [_feature(tier=tier, hydro=hydro, utility=utility)] * n_features
    _write_geojson(tmp_path / "spiderweb_overlay_candidates.geojson", features)
    _write_gap_audit(tmp_path / "spiderweb_gap_audit.json")
    return CalibrationDriver(str(tmp_path)).run()


def test_compare_runs_returns_dict(tmp_path):
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir()
    dir_b.mkdir()
    report_a = _run_report(dir_a, 5)
    report_b = _run_report(dir_b, 10)
    delta = CalibrationDriver.compare_runs(report_a, report_b)
    assert isinstance(delta, dict)
    assert "metric_deltas" in delta
    assert "candidate_count_a" in delta
    assert "candidate_count_b" in delta


def test_compare_runs_candidate_counts(tmp_path):
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir()
    dir_b.mkdir()
    report_a = _run_report(dir_a, 3)
    report_b = _run_report(dir_b, 7)
    delta = CalibrationDriver.compare_runs(report_a, report_b)
    assert delta["candidate_count_a"] == 3
    assert delta["candidate_count_b"] == 7


def test_compare_runs_zero_delta_identical(tmp_path):
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir()
    dir_b.mkdir()
    report_a = _run_report(dir_a, 5)
    report_b = _run_report(dir_b, 5)
    delta = CalibrationDriver.compare_runs(report_a, report_b)
    for key, val in delta["metric_deltas"].items():
        if val is not None:
            assert abs(val) < 1e-4, f"Expected zero delta for {key}, got {val}"


def test_compare_runs_status_keys(tmp_path):
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir()
    dir_b.mkdir()
    report_a = _run_report(dir_a, 5)
    report_b = _run_report(dir_b, 5)
    delta = CalibrationDriver.compare_runs(report_a, report_b)
    assert "status_a" in delta
    assert "status_b" in delta
