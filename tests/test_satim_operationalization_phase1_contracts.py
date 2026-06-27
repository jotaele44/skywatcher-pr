import json
from pathlib import Path

from fr24.calibration.satim_candidate_extraction import normalize_candidate


ROOT = Path(__file__).resolve().parents[1]


def test_satim_visual_ledger_schema_loads():
    schema_path = ROOT / "schemas" / "satim_visual_ledger.schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    assert payload["title"] == "SATIM Visual Ledger Row"
    assert payload["properties"]["schema_version"]["const"] == "satim.visual_ledger.v1"
    assert "visual_id" in payload["required"]
    assert "feature_scores" in payload["required"]


def test_tile_artifact_ledger_schema_loads():
    schema_path = ROOT / "schemas" / "tile_artifact_ledger.schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    assert payload["title"] == "SATIM Tile Artifact Ledger Row"
    assert payload["properties"]["schema_version"]["const"] == "satim.tile_artifact_ledger.v1"
    assert "artifact_class" in payload["properties"]
    assert "likelihoods" in payload["required"]


def test_normalize_candidate_outputs_visual_ledger_contract():
    row = normalize_candidate({
        "visual_id": "SATIM-VIS-TEST_001",
        "source_image_id": "IMG_001",
        "source_uri": "fixtures://satim/IMG_001.png",
        "capture_datetime_utc": "2026-06-27T00:00:00Z",
        "aoi_id": "AOI_TEST",
        "candidate_kind": "linear_boundary",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-66.0, 18.0], [-66.1, 18.1]],
            "bbox": [-66.1, 18.0, -66.0, 18.1],
        },
        "straightness": 1.2,
        "radiometric_delta": 0.8,
        "classification": "probable_tile_seam",
        "confidence": 1.5,
    })

    assert row["schema_version"] == "satim.visual_ledger.v1"
    assert row["visual_id"] == "SATIM-VIS-TEST_001"
    assert row["candidate_kind"] == "linear_boundary"
    assert row["classification"] == "probable_tile_seam"
    assert row["confidence"] == 1.0
    assert row["feature_scores"]["straightness"] == 1.0
    assert row["feature_scores"]["radiometric_delta"] == 0.8
    assert row["feature_scores"]["track_line_overlap"] == 0.0
    assert row["review_state"] == "unreviewed"


def test_normalize_candidate_rejects_unknown_candidate_kind():
    try:
        normalize_candidate({
            "visual_id": "SATIM-VIS-TEST_002",
            "source_image_id": "IMG_002",
            "source_uri": "fixtures://satim/IMG_002.png",
            "capture_datetime_utc": "2026-06-27T00:00:00Z",
            "aoi_id": "AOI_TEST",
            "candidate_kind": "unsupported_kind",
            "geometry": {"type": "Point", "coordinates": [-66.0, 18.0]},
        })
    except ValueError as exc:
        assert "unsupported SATIM candidate_kind" in str(exc)
    else:
        raise AssertionError("normalize_candidate should reject unsupported candidate kinds")
