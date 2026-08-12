"""L5 classifier selection (flag-gated). Default is tile_seam_shadow; the
synthetic_boundary mode is offered as an alternative and normalized to the
canonical L5 layer slot. Unknown modes raise."""

from __future__ import annotations

import csv

import pytest

from fr24 import satim_engine


def _write_candidates(path):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["candidate_id", "straightness", "radiometric_delta", "straight", "radiometric"])
        w.writerow(["c1", "0.9", "0.6", "0.9", "0.6"])
    return str(path)


def _write_strict_candidates(path, *, screen_locked):
    # A candidate that satisfies every strict clause except (optionally) screen-lock.
    cols = {
        "candidate_id": "c1",
        "straight_boundary_score": "0.9",
        "radiometric_discontinuity_score": "0.6",
        "screen_locked_score": str(screen_locked),
        "multi_date_persistence": "0.1",
        "dem_hillshade_alignment": "0.0",
        "track_line_overlap": "0.0",
        "ui_overlay_overlap": "0.0",
    }
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols))
        w.writeheader()
        w.writerow(cols)
    return str(path)


def test_default_tile_seam_mode(tmp_path):
    out = satim_engine.run_l5("tile_seam_shadow", _write_candidates(tmp_path / "c.csv"))
    assert out["layer"] == "L5_tile_seam_shadow"
    assert out["metrics"]["l5_mode"] == "tile_seam_shadow"


def test_synthetic_mode_is_normalized_to_canonical_slot(tmp_path):
    out = satim_engine.run_l5("synthetic_boundary", _write_candidates(tmp_path / "c.csv"))
    # synthetic classifier natively emits layer 'L5_synthetic_boundary'; the
    # runner normalizes it so readiness aggregation still recognizes L5.
    assert out["layer"] == "L5_tile_seam_shadow"
    assert out["metrics"]["l5_mode"] == "synthetic_boundary"


def test_unknown_mode_raises(tmp_path):
    with pytest.raises(ValueError):
        satim_engine.run_l5("nonesuch", _write_candidates(tmp_path / "c.csv"))


def test_strict_mode_promotes_when_all_clauses_met(tmp_path):
    # screen_locked_score high → the strict AND-gate promotes a tile seam.
    out = satim_engine.run_l5("strict", _write_strict_candidates(tmp_path / "c.csv", screen_locked=0.9))
    assert out["layer"] == "L5_tile_seam_shadow"
    assert out["metrics"]["l5_mode"] == "strict"
    assert out["metrics"]["decision_counts"]["probable_tile_seam"] == 1


def test_strict_mode_is_inert_without_screen_lock(tmp_path):
    # screen_locked_score 0.0 (production default: no extractor) → nothing promoted,
    # and an explicit finding is emitted.
    out = satim_engine.run_l5("strict", _write_strict_candidates(tmp_path / "c.csv", screen_locked=0.0))
    assert out["metrics"]["decision_counts"]["probable_tile_seam"] == 0
    assert any("inert" in f["detail"] for f in out["findings"])


def test_both_modes_share_result_shape(tmp_path):
    csv_path = _write_candidates(tmp_path / "c.csv")
    a = satim_engine.run_l5("tile_seam_shadow", csv_path)
    b = satim_engine.run_l5("synthetic_boundary", csv_path)
    assert set(a) == set(b)  # same LayerCalibrationResult top-level keys
    assert a["status"] == b["status"] == "READY"
