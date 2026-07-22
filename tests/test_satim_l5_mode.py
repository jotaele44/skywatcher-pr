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
        satim_engine.run_l5("strict", _write_candidates(tmp_path / "c.csv"))


def test_both_modes_share_result_shape(tmp_path):
    csv_path = _write_candidates(tmp_path / "c.csv")
    a = satim_engine.run_l5("tile_seam_shadow", csv_path)
    b = satim_engine.run_l5("synthetic_boundary", csv_path)
    assert set(a) == set(b)  # same LayerCalibrationResult top-level keys
    assert a["status"] == b["status"] == "READY"
