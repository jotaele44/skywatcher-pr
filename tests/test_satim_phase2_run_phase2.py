"""End-to-end offline test for the SATIM Phase-2 driver (fr24/calibration/run_phase2.py).

Runs the bundled AOI control fixture through the full chain
(detect_raster_candidates -> patch_candidate_with_gis_scores ->
validate_candidate_across_dates -> visual-ledger CSV) with no image IO and no
network. Pure stdlib (json/csv) — pandas is not involved.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from fr24.calibration.run_phase2 import (
    LEDGER_COLUMNS,
    load_fixture,
    main,
    run_driver,
    write_ledger_csv,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "satim_phase2" / "aoi_detections.json"


def _rows_by_image(rows):
    return {row["source_image_id"]: row for row in rows}


def test_fixture_loads_three_aoi_blocks():
    aois = load_fixture(FIXTURE)
    assert len(aois) == 3
    assert {block["aoi_id"] for block in aois} == {"PR_TILE_SEAM_CONTROL", "PR_AIRPORT_BQN_APRON"}


def test_run_driver_emits_visual_ledger_rows():
    rows = run_driver(load_fixture(FIXTURE))
    assert len(rows) == 3
    for row in rows:
        assert row["schema_version"] == "satim.visual_ledger.v1"
        assert row["review_state"] == "needs_review"
        # multi_date_persistence is threaded from the validator into feature_scores.
        assert row["feature_scores"]["multi_date_persistence"] == row["multidate_persistence"]


def test_cross_epoch_disappearing_seam_is_mixed_epoch_artifact():
    row = _rows_by_image(run_driver(load_fixture(FIXTURE)))["IMG_TILE_SEAM_CONTROL_2024_01"]
    # GIS overlay explains the boundary (infra_alignment == 1.0 on a tile-seam).
    assert row["feature_scores"]["infrastructure_alignment"] == 1.0
    assert "infrastructure_explains_boundary" in row["contradiction_flags"]
    # A low-persistence cross-epoch comparison marks it a mixed-epoch artifact.
    assert row["multidate_epoch_class"] == "cross_epoch"
    assert row["multidate_classification_hint"] == "mixed_epoch_artifact"
    assert row["multidate_decision"] == "review"


def test_single_still_seam_claim_is_blocked():
    row = _rows_by_image(run_driver(load_fixture(FIXTURE)))["IMG_TILE_SEAM_CONTROL_SINGLE_STILL"]
    # No cross-epoch comparison -> promotion blocked, contract-critical flag set.
    assert row["multidate_epoch_class"] == "insufficient_cross_epoch"
    assert row["multidate_decision"] == "cross_source_required"
    assert "single_still_seam_claim" in row["contradiction_flags"]


def test_persistent_cross_epoch_is_probable_ground_feature():
    row = _rows_by_image(run_driver(load_fixture(FIXTURE)))["IMG_BQN_APRON_2024_03"]
    # gis_metrics (raw) normalized through the metric adapter.
    assert row["feature_scores"]["airport_alignment"] == 0.95
    assert row["multidate_classification_hint"] == "probable_ground_feature"
    assert row["multidate_persistence"] >= 0.65
    # AOI-level provenance is carried onto the row.
    assert row["municipality"] == "Aguadilla"


def test_source_dates_compared_is_carried_onto_each_row():
    rows = _rows_by_image(run_driver(load_fixture(FIXTURE)))
    # Required ledger field: the cross-epoch capture dates behind the decision.
    assert rows["IMG_TILE_SEAM_CONTROL_2024_01"]["source_dates_compared"] == [
        "2022-01-10T00:00:00Z"
    ]
    assert rows["IMG_BQN_APRON_2024_03"]["source_dates_compared"] == [
        "2022-03-05T00:00:00Z"
    ]
    # The single-still block has no comparison imagery -> empty (but present) list.
    assert rows["IMG_TILE_SEAM_CONTROL_SINGLE_STILL"]["source_dates_compared"] == []


def test_write_ledger_csv_roundtrips(tmp_path):
    rows = run_driver(load_fixture(FIXTURE))
    out = tmp_path / "ledger.csv"
    written = write_ledger_csv(rows, out)
    assert written == 3

    with out.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert list(reader.fieldnames) == list(LEDGER_COLUMNS)
        csv_rows = list(reader)
    assert len(csv_rows) == 3
    # JSON-encoded cells decode back to the structured values.
    first = _rows_by_image(rows)["IMG_TILE_SEAM_CONTROL_2024_01"]
    csv_first = _rows_by_image(csv_rows)["IMG_TILE_SEAM_CONTROL_2024_01"]
    assert json.loads(csv_first["feature_scores"]) == first["feature_scores"]
    assert json.loads(csv_first["geometry"]) == first["geometry"]
    assert json.loads(csv_first["contradiction_flags"]) == first["contradiction_flags"]
    # source_dates_compared is a required ledger field, JSON-encoded in its cell.
    assert "source_dates_compared" in reader.fieldnames
    assert json.loads(csv_first["source_dates_compared"]) == ["2022-01-10T00:00:00Z"]


def test_main_cli_writes_csv(tmp_path, capsys):
    out = tmp_path / "cli_ledger.csv"
    rc = main(["--input", str(FIXTURE), "--output", str(out)])
    assert rc == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "satim.visual_ledger.v1" in captured.out
    with out.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 3


def test_main_cli_missing_input_fails_cleanly(tmp_path):
    rc = main(["--input", str(tmp_path / "nope.json"), "--output", str(tmp_path / "o.csv")])
    assert rc == 1
