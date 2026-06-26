"""Tests for the empirical SATIM layer: ground truth, fit, corpus tooling."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Script modules live under scripts/, not an importable package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import satim_cross_source_check as xsrc  # noqa: E402
import satim_harvest_review_labels as harvest  # noqa: E402

from fr24.manual_review_queue import ManualReviewQueue  # noqa: E402
from satim_calibration import load_calibration_set  # noqa: E402
from satim_fit import (  # noqa: E402
    emit_fp_classes_yaml,
    fit_calibration,
    fit_promotion_thresholds,
    fit_scoring_adjustments,
)
from satim_ground_truth import append_ground_truth, normalize_fp_class, read_ground_truth  # noqa: E402
from satim_render_diff import autolabel_render_diff, classify_render_diff  # noqa: E402

MOCA_SET = REPO_ROOT / "data" / "satim_calibration" / "moca_fr24_2025"
CONTROL_SET = REPO_ROOT / "data" / "satim_calibration" / "control_moca_groundtruth"
FITTER = "scripts/fit_satim_calibration.py"
VALIDATOR = "scripts/validate_satim_calibration.py"


def _gt(fp_class, confidence, is_fp, source="cross_source", image="img"):
    return {
        "image_id": image, "false_positive_class": fp_class, "confidence": confidence,
        "is_false_positive": is_fp, "source": source,
    }


# --- normalize / ground-truth store -----------------------------------------
class TestGroundTruthStore:
    def test_normalize_uses_canonical_and_aliases(self):
        assert normalize_fp_class("palm") == "PALM"
        assert normalize_fp_class("LAVA") is None
        # aliases (a set's false_positive_aliases) resolve compound classes.
        aliases = {"TREE_CROWN": "PALM", "SHADOW_OR_COMPRESSION": "SHADOW"}
        assert normalize_fp_class("TREE_CROWN", aliases) == "PALM"
        assert normalize_fp_class("SHADOW_OR_COMPRESSION", aliases) == "SHADOW"

    def test_append_and_read_roundtrip(self, tmp_path):
        path = tmp_path / "ground_truth.csv"
        assert append_ground_truth(path, [_gt("PALM", "0.9", "1")]) == 1
        rows = read_ground_truth(path)
        assert rows[0]["false_positive_class"] == "PALM"
        assert rows[0]["is_false_positive"] == "1"

    def test_append_dedupes_by_feature_and_source(self, tmp_path):
        path = tmp_path / "ground_truth.csv"
        append_ground_truth(path, [_gt("PALM", "0.9", "1", image="a")])
        again = append_ground_truth(
            path,
            [_gt("PALM", "0.9", "1", image="a"), _gt("PALM", "0.9", "1", image="a", source="esri")],
        )
        assert again == 1
        assert len(read_ground_truth(path)) == 2

    def test_append_drops_unresolvable_rows(self, tmp_path):
        path = tmp_path / "ground_truth.csv"
        written = append_ground_truth(
            path,
            [_gt("VOLCANO", "0.9", "1"), _gt("PALM", "x", "1"), _gt("PALM", "0.5", "maybe"),
             _gt("WATER", "0.5", "tp")],
        )
        assert written == 1
        assert read_ground_truth(path)[0]["false_positive_class"] == "WATER"


# --- fit ---------------------------------------------------------------------
class TestFit:
    def test_confident_artifact_class_gets_strong_penalty(self):
        adjustments, stats = fit_scoring_adjustments([("PALM", 0.9, False), ("PALM", 0.8, False)])
        assert adjustments["PALM"] == pytest.approx(-0.85, abs=1e-6)
        assert stats["PALM"].precision == 0.0

    def test_reliable_class_gets_no_penalty(self):
        adjustments, _ = fit_scoring_adjustments([("WATER", 0.6, True), ("WATER", 0.7, True)])
        assert adjustments["WATER"] == 0.0

    def test_thresholds_monotonic_and_in_range(self):
        parsed = [
            ("PALM", 0.95, True), ("WATER", 0.85, True), ("FR24_3D_RENDER", 0.3, False),
            ("SHADOW", 0.2, False), ("FR24_3D_RENDER", 0.25, False),
        ]
        adj, _ = fit_scoring_adjustments(parsed)
        thr = fit_promotion_thresholds(parsed, adj)
        vals = [thr["review"], thr["cross_source_required"], thr["promote_to_candidate"]]
        assert vals == sorted(vals)
        assert all(0.0 <= v <= 1.0 for v in vals)

    def test_empty_returns_defaults(self):
        result = fit_calibration([])
        assert result.n_rows == 0
        assert result.promotion_thresholds["review"] == pytest.approx(0.55)

    def test_emit_preserves_descriptions_and_aliases(self):
        original = (MOCA_SET / "false_positive_classes.yaml").read_text()
        out = emit_fp_classes_yaml(
            original, "SATIM-CAL-X_v2",
            {"PALM": -0.5, "SHADOW": -0.1, "WATER": -0.2, "FR24_3D_RENDER": -0.4},
            {"review": 0.5, "cross_source_required": 0.6, "promote_to_candidate": 0.7},
        )
        assert "calibration_id: SATIM-CAL-X_v2" in out
        assert "suppress_when:" in out                       # description block preserved
        assert "false_positive_aliases:" in out              # main's alias block preserved
        assert "TREE_CROWN: PALM" in out
        assert "PALM: -0.5" in out
        assert out.count("scoring_adjustments:") == 1


# --- fitter script emits a validatable v2 set --------------------------------
class TestFitterScript:
    def test_refit_emits_validatable_set(self, tmp_path):
        src = tmp_path / "set"
        shutil.copytree(MOCA_SET, src)
        append_ground_truth(
            src / "ground_truth.csv",
            [_gt("PALM", "0.9", "1", image="f1"), _gt("WATER", "0.9", "0", image="f2"),
             _gt("FR24_3D_RENDER", "0.7", "1", image="f3"), _gt("SHADOW", "0.5", "0", image="f4")],
        )
        out = tmp_path / "set_v2"
        result = subprocess.run(
            [sys.executable, FITTER, str(src), "--out", str(out)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert not (out / "ground_truth.csv").exists()
        # Calibration id bumped consistently across the set (validator cross-checks).
        cs = load_calibration_set(out)
        assert cs.calibration_id.endswith("_v2")
        validated = subprocess.run(
            [sys.executable, VALIDATOR, str(out)], cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        assert validated.returncode == 0, validated.stdout

    def test_refit_without_labels_fails_cleanly(self, tmp_path):
        src = tmp_path / "set"
        shutil.copytree(MOCA_SET, src)
        (src / "ground_truth.csv").unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, FITTER, str(src), "--out", str(tmp_path / "v2")],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "no labeled rows" in (result.stderr + result.stdout)


# --- cross-source join -------------------------------------------------------
class TestCrossSource:
    def test_join_maps_verdicts_and_resolves_aliases(self):
        cs = load_calibration_set(MOCA_SET)
        aliases = cs.false_positive_aliases
        # Pick a label whose fp class resolves (TREE_CROWN -> PALM).
        label = next(l for l in cs.labels if l.false_positive_class == "TREE_CROWN")
        verdicts = {(label.image_id, "PALM"): {"verdict": "confirmed", "source": "esri"}}
        rows = xsrc.build_ground_truth_rows([label], verdicts, aliases)
        assert rows and rows[0]["false_positive_class"] == "PALM"
        assert rows[0]["is_false_positive"] == "0"
        assert rows[0]["source"] == "esri"

    def test_refuted_marks_false_positive(self):
        cs = load_calibration_set(MOCA_SET)
        label = next(l for l in cs.labels if l.false_positive_class == "FR24_3D_RENDER")
        verdicts = {(label.image_id, "FR24_3D_RENDER"): {"verdict": "fr24_only", "source": "s2"}}
        rows = xsrc.build_ground_truth_rows([label], verdicts, cs.false_positive_aliases)
        assert rows[0]["is_false_positive"] == "1"


# --- review-queue harvest ----------------------------------------------------
class TestHarvest:
    def test_resolution_mapping(self):
        assert harvest.resolution_to_flag("confirmed real feature") == "0"
        assert harvest.resolution_to_flag("rejected as artifact") == "1"
        assert harvest.resolution_to_flag("deferred") is None

    def test_harvest_end_to_end_with_real_queue(self, tmp_path):
        queue = ManualReviewQueue(str(tmp_path / "queue"))
        item_id = queue.add_item(
            "quality_issue", "/tmp/f1.jpg", "satim review",
            metadata={"image_id": "f1", "false_positive_class": "PALM", "confidence": 0.9},
        )
        queue.mark_reviewed(item_id, resolution="confirmed real feature")
        rows = harvest.harvest_rows(queue.get_all(status="reviewed"))
        assert rows and rows[0]["false_positive_class"] == "PALM"
        assert rows[0]["is_false_positive"] == "0"


# --- render-diff + control set ----------------------------------------------
class TestRenderDiffAndControl:
    def test_varying_presence_is_artifact(self):
        assert classify_render_diff({"z16": True, "z18": False}) == "FR24_3D_RENDER"

    def test_invariant_presence_not_labeled(self):
        assert classify_render_diff({"z16": True, "z18": True}) is None
        assert classify_render_diff({"z16": True}) is None

    def test_autolabel_emits_fp_rows(self):
        observations = [
            {"feature_id": "a", "param_set": "z16", "present": "1", "image_id": "imgA"},
            {"feature_id": "a", "param_set": "z18", "present": "0", "image_id": "imgA"},
            {"feature_id": "b", "param_set": "z16", "present": "1"},
            {"feature_id": "b", "param_set": "z18", "present": "1"},
        ]
        rows = autolabel_render_diff(observations)
        assert len(rows) == 1
        assert rows[0]["image_id"] == "imgA"
        assert rows[0]["false_positive_class"] == "FR24_3D_RENDER"
        assert float(rows[0]["confidence"]) == pytest.approx(0.5)

    def test_control_set_loads_and_validates(self):
        # The control set is a real, discoverable calibration set.
        cs = load_calibration_set(CONTROL_SET)
        assert cs.calibration_id == "SATIM-CAL-CONTROL-MOCA_v1"
        result = subprocess.run(
            [sys.executable, VALIDATOR, str(CONTROL_SET)], cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout
