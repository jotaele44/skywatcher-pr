from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "data" / "satim_calibration"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_moca_calibration_contains_required_visual_false_positive_families() -> None:
    rows = _rows(CAL / "moca_fr24_2025" / "labels.csv")
    classes = {row["false_positive_class"] for row in rows}
    assert "PALM" in classes
    assert "WATER" in classes
    assert "FR24_3D_RENDER" in classes
    assert any("SHADOW" in value for value in classes)


def test_control_set_certifies_tile_seam_as_render_not_real_world_boundary() -> None:
    rows = _rows(CAL / "control_moca_groundtruth" / "labels.csv")
    seam = next(row for row in rows if row["image_id"] == "control_render_01")
    assert seam["feature_class"] == "confirmed_tile_seam"
    assert seam["false_positive_class"] == "FR24_3D_RENDER"
    assert "absent from reference imagery" in seam["notes"]


def test_control_palm_is_tree_class_not_species_identity() -> None:
    rows = _rows(CAL / "control_moca_groundtruth" / "labels.csv")
    palm = next(row for row in rows if row["image_id"] == "control_palm_01")
    assert palm["feature_class"] == "confirmed_palm_crown"
    assert palm["false_positive_class"] == "PALM"
    assert "species" not in palm["feature_class"].lower()


def test_control_water_supports_water_presence_not_hydrographic_form() -> None:
    rows = _rows(CAL / "control_moca_groundtruth" / "labels.csv")
    water = next(row for row in rows if row["image_id"] == "control_water_01")
    assert water["feature_class"] == "confirmed_pool"
    assert water["false_positive_class"] == "WATER"
    assert water["feature_class"] not in {"river", "stream", "canal", "reservoir"}


def test_ambiguous_moca_shadow_labels_remain_ambiguous_controls() -> None:
    rows = _rows(CAL / "moca_fr24_2025" / "labels.csv")
    ambiguous = [row for row in rows if row["feature_class"] == "unusual_object_or_shadow"]
    assert ambiguous
    assert all(float(row["confidence"]) < 0.5 for row in ambiguous)
    assert {row["false_positive_class"] for row in ambiguous} <= {"SHADOW", "TREE_CROWN"}
