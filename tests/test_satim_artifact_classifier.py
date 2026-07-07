from __future__ import annotations

import csv
from pathlib import Path

from scripts.classify_satim_artifacts import classify_csv, classify_text


def test_unknown_defaults_to_hold_review() -> None:
    assert classify_text("unclassified visual texture") == ("HOLD_REVIEW", "low")


def test_track_line_classification() -> None:
    assert classify_text("FR24 playback diagonal track line") == ("TRACK_LINE", "high")


def test_tile_seam_classification() -> None:
    assert classify_text("rectilinear tile seam and mixed epoch boundary") == ("TILE_SEAM", "medium")


def test_csv_classifier_does_not_preserve_structural_signal(tmp_path: Path) -> None:
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    input_csv.write_text(
        "artifact_id,event_id,page,artifact_class,description,artifact_risk,impact_on_analysis\n"
        "A1,E1,1,STRUCTURAL_SIGNAL,unclassified visual texture,,\n",
        encoding="utf-8",
    )

    classify_csv(input_csv, output_csv)

    with output_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["artifact_class"] == "HOLD_REVIEW"
    assert rows[0]["promotion_status"] == "hold_artifact_control"
