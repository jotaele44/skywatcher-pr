"""Fit-harness gate: deterministic, monotonic threshold derivation from a
synthetic labeled ground_truth (no operational data)."""

from __future__ import annotations

import csv
import json

import satim_fit


SYNTHETIC_ROWS = [
    {"image_id": "a1", "false_positive_class": "PALM", "confidence": "0.90", "is_false_positive": "1", "source": "syn"},
    {"image_id": "a2", "false_positive_class": "PALM", "confidence": "0.80", "is_false_positive": "1", "source": "syn"},
    {"image_id": "w1", "false_positive_class": "WATER", "confidence": "0.95", "is_false_positive": "1", "source": "syn"},
    {"image_id": "s1", "false_positive_class": "SHADOW", "confidence": "0.40", "is_false_positive": "0", "source": "syn"},
    {"image_id": "s2", "false_positive_class": "SHADOW", "confidence": "0.55", "is_false_positive": "0", "source": "syn"},
]


def test_fit_is_deterministic():
    r1 = satim_fit.fit_calibration(SYNTHETIC_ROWS)
    r2 = satim_fit.fit_calibration(SYNTHETIC_ROWS)
    assert satim_fit.fit_result_to_dict(r1) == satim_fit.fit_result_to_dict(r2)


def test_thresholds_are_monotonic_and_bounded():
    r = satim_fit.fit_calibration(SYNTHETIC_ROWS)
    t = r.promotion_thresholds
    assert 0.0 <= t["review"] <= t["cross_source_required"] <= t["promote_to_candidate"] <= 1.0


def test_scoring_adjustments_are_suppressive():
    r = satim_fit.fit_calibration(SYNTHETIC_ROWS)
    # validator contract: every adjustment in [-1, 0]
    for cls, adj in r.scoring_adjustments.items():
        assert -1.0 <= adj <= 0.0, (cls, adj)


def test_cli_emits_json(tmp_path, capsys):
    csv_path = tmp_path / "gt.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(SYNTHETIC_ROWS[0].keys()))
        w.writeheader()
        w.writerows(SYNTHETIC_ROWS)
    rc = satim_fit.main(["--ground-truth", str(csv_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_rows"] == len(SYNTHETIC_ROWS)
    assert set(out["promotion_thresholds"]) == {"review", "cross_source_required", "promote_to_candidate"}
