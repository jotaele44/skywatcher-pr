"""Tests for the SATIM visual-analysis calibration engine."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from satim_calibration import (
    SATIM_ENGINE_VERSION,
    CalibrationLabel,
    load_all_calibration_sets,
    load_calibration_set,
    promotion_decision,
    score_calibration_set,
    score_label,
)


def _synthetic_label(false_positive_class: str, confidence: float) -> CalibrationLabel:
    return CalibrationLabel(
        image_id="synthetic",
        source_page_or_frame="page_01",
        time_local="00:00",
        aircraft="C6038",
        altitude_ft=800,
        ground_speed_mph=44,
        marker_type="circle",
        feature_class="synthetic_feature",
        false_positive_class=false_positive_class,
        confidence=confidence,
        notes="",
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCA_SET = REPO_ROOT / "data" / "satim_calibration" / "moca_fr24_2025"
VALIDATOR = REPO_ROOT / "scripts" / "validate_satim_calibration.py"

DEFAULT_THRESHOLDS = {
    "review": 0.55,
    "cross_source_required": 0.70,
    "promote_to_candidate": 0.80,
}


# --- loading ----------------------------------------------------------------
def test_load_moca_set_shape() -> None:
    cs = load_calibration_set(MOCA_SET)
    assert cs.calibration_id == "SATIM-CAL-MOCA-C6038_v1"
    assert cs.evidence_tier == "T2_operational_screenshot"
    assert len(cs.labels) == 12
    assert len({lbl.source_page_or_frame for lbl in cs.labels}) == 4
    assert len(cs.marker_classes) == 6
    assert len(cs.false_positive_classes) == 4
    assert cs.scoring_adjustments == {
        "PALM": -0.25,
        "SHADOW": -0.20,
        "WATER": -0.30,
        "FR24_3D_RENDER": -0.35,
    }
    assert cs.aircraft["primary_label"] == "C6038"


def test_discovery_finds_the_set() -> None:
    sets = load_all_calibration_sets(REPO_ROOT / "data" / "satim_calibration")
    ids = {s.calibration_id for s in sets}
    assert "SATIM-CAL-MOCA-C6038_v1" in ids


# --- scoring ----------------------------------------------------------------
def test_score_label_fr24_render_is_suppressed() -> None:
    cs = load_calibration_set(MOCA_SET)
    label = next(l for l in cs.labels if l.feature_class == "roof_or_building_edge")
    scored = score_label(label, cs.scoring_adjustments, cs.promotion_thresholds)
    assert scored.raw_confidence == 0.70
    assert scored.adjustment == -0.35
    assert scored.adjusted_score == 0.35
    assert scored.decision == "suppressed"
    assert scored.unknown_false_positive_class is False


def test_score_label_palm_lands_in_review() -> None:
    cs = load_calibration_set(MOCA_SET)
    label = next(l for l in cs.labels if l.false_positive_class == "PALM")
    scored = score_label(label, cs.scoring_adjustments, cs.promotion_thresholds)
    # 0.90 + (-0.25) = 0.65 -> review band
    assert scored.adjusted_score == 0.65
    assert scored.decision == "review"


def test_alias_resolves_to_canonical_class() -> None:
    cs = load_calibration_set(MOCA_SET)
    # TREE_CROWN -> PALM (-0.25); raw 0.35 -> 0.10 suppressed.
    label = next(l for l in cs.labels if l.false_positive_class == "TREE_CROWN")
    scored = score_label(
        label, cs.scoring_adjustments, cs.promotion_thresholds, cs.false_positive_aliases
    )
    assert scored.resolved_false_positive_class == "PALM"
    assert scored.resolution_status == "aliased"
    assert scored.adjustment == -0.25
    assert scored.adjusted_score == 0.10
    assert scored.decision == "suppressed"
    assert scored.unknown_false_positive_class is False


def test_unmapped_class_is_unknown_with_zero_adjustment() -> None:
    cs = load_calibration_set(MOCA_SET)
    label = _synthetic_label("NONSENSE_CLASS", 0.60)
    scored = score_label(
        label, cs.scoring_adjustments, cs.promotion_thresholds, cs.false_positive_aliases
    )
    assert scored.adjustment == 0.0
    assert scored.adjusted_score == scored.raw_confidence
    assert scored.resolution_status == "unknown"
    assert scored.unknown_false_positive_class is True


def test_canonical_class_resolution_status() -> None:
    cs = load_calibration_set(MOCA_SET)
    label = next(l for l in cs.labels if l.false_positive_class == "PALM")
    scored = score_label(
        label, cs.scoring_adjustments, cs.promotion_thresholds, cs.false_positive_aliases
    )
    assert scored.resolution_status == "resolved"


@pytest.mark.parametrize(
    "adjusted,expected",
    [
        (0.80, "candidate"),
        (0.95, "candidate"),
        (0.79, "cross_source_required"),
        (0.70, "cross_source_required"),
        (0.69, "review"),
        (0.55, "review"),
        (0.54, "suppressed"),
        (0.0, "suppressed"),
    ],
)
def test_promotion_decision_bands(adjusted: float, expected: str) -> None:
    assert promotion_decision(adjusted, DEFAULT_THRESHOLDS) == expected


def test_score_calibration_set_summary() -> None:
    cs = load_calibration_set(MOCA_SET)
    summary = score_calibration_set(cs)
    assert summary["counts"]["labels"] == 12
    assert sum(summary["decision_breakdown"].values()) == 12
    # adjusted mean must be lower than raw mean (suppression is net-negative)
    assert summary["score_summary"]["mean_adjusted"] < summary["score_summary"]["mean_raw"]
    # all compound classes now resolve via aliases -> no unresolved warnings
    assert summary["warnings"] == []
    assert summary["decision_breakdown"] == {"suppressed": 9, "review": 3}
    assert summary["resolution_breakdown"] == {"resolved": 8, "aliased": 4}
    assert all(0.0 <= row["adjusted_score"] <= 1.0 for row in summary["labels"])


def test_summary_promotion_gate_and_candidates() -> None:
    cs = load_calibration_set(MOCA_SET)
    summary = score_calibration_set(cs)
    gate = summary["promotion_gate"]
    assert "frame_to_frame_repeatability" in gate["checks"]
    assert len(gate["required_cross_sources"]) == 4
    assert gate["status"] == "pending"
    # candidates == non-suppressed labels
    assert summary["counts"]["candidates"] == len(summary["candidates"]) == 3
    assert all(c["decision"] != "suppressed" for c in summary["candidates"])


def test_summary_repeatability_signal() -> None:
    cs = load_calibration_set(MOCA_SET)
    summary = score_calibration_set(cs)
    rec = summary["repeatability"]["by_feature_class"]
    # canopy_texture_smudge is marked in 3 distinct frames (09, 10, 12)
    assert rec["canopy_texture_smudge"] == 3
    assert "canopy_texture_smudge" in summary["repeatability"]["recurring_feature_classes"]


def test_summary_provenance() -> None:
    cs = load_calibration_set(MOCA_SET)
    summary = score_calibration_set(cs)
    prov = summary["provenance"]
    assert prov["engine_version"] == SATIM_ENGINE_VERSION
    files = {i["file"] for i in prov["inputs"]}
    assert files == {
        "registry_entry.yaml",
        "marker_legend.yaml",
        "false_positive_classes.yaml",
        "labels.csv",
    }
    assert all(len(i["sha256"]) == 64 for i in prov["inputs"])


# --- validator (subprocess, matching repo convention) -----------------------
def _run_validator(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(target)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_validator_passes_on_real_set() -> None:
    result = _run_validator(MOCA_SET)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VALIDATION PASSED" in result.stdout
    # all compound classes are aliased to canonical, so the set is now clean
    assert "WARNINGS" not in result.stdout


def test_validator_fails_on_bad_alias_target(tmp_path: Path) -> None:
    broken = tmp_path / "bad_alias_set"
    shutil.copytree(MOCA_SET, broken)
    fp = broken / "false_positive_classes.yaml"
    fp.write_text(
        fp.read_text(encoding="utf-8") + "  TREE_CROWN: NOT_A_CANONICAL_CLASS\n",
        encoding="utf-8",
    )
    result = _run_validator(broken)
    assert result.returncode == 1
    assert "not a canonical scoring class" in result.stdout


def test_validator_fails_on_missing_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken_set"
    shutil.copytree(MOCA_SET, broken)
    (broken / "labels.csv").unlink()
    result = _run_validator(broken)
    assert result.returncode == 1
    assert "missing required files" in result.stdout


def test_validator_fails_on_bad_confidence(tmp_path: Path) -> None:
    broken = tmp_path / "bad_conf_set"
    shutil.copytree(MOCA_SET, broken)
    labels = broken / "labels.csv"
    text = labels.read_text(encoding="utf-8")
    # push one confidence value out of [0, 1]
    text = text.replace(",0.70,", ",1.70,", 1)
    labels.write_text(text, encoding="utf-8")
    result = _run_validator(broken)
    assert result.returncode == 1
    assert "confidence" in result.stdout


def test_validator_fails_on_unknown_marker_type(tmp_path: Path) -> None:
    broken = tmp_path / "bad_marker_set"
    shutil.copytree(MOCA_SET, broken)
    labels = broken / "labels.csv"
    text = labels.read_text(encoding="utf-8")
    text = text.replace(",straight_line,", ",zigzag,", 1)
    labels.write_text(text, encoding="utf-8")
    result = _run_validator(broken)
    assert result.returncode == 1
    assert "not defined in marker_legend" in result.stdout
