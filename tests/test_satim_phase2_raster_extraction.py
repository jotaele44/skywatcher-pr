from fr24.calibration.satim_raster_candidate_extraction import detect_raster_candidates


def test_detect_raster_candidates_emits_visual_ledger_rows():
    rows = detect_raster_candidates(
        [
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-66.0, 18.0], [-66.1, 18.1]],
                },
                "boundary_length_px": 80,
                "straightness": 0.91,
                "radiometric_delta": 0.72,
            }
        ],
        source_image_id="IMG_PHASE2_001",
        source_uri="fixtures://satim/phase2/IMG_PHASE2_001.png",
        capture_datetime_utc="2026-07-01T00:00:00Z",
        aoi_id="PR_TILE_SEAM_CONTROL",
    )

    assert len(rows) == 1
    assert rows[0]["schema_version"] == "satim.visual_ledger.v1"
    assert rows[0]["visual_id"] == "SATIM-VIS-IMG_PHASE2_001_0001"
    assert rows[0]["feature_scores"]["straightness"] == 0.91
    assert rows[0]["feature_scores"]["radiometric_delta"] == 0.72


def test_detect_raster_candidates_filters_short_low_signal_boundaries():
    rows = detect_raster_candidates(
        [
            {
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "boundary_length_px": 4,
                "straightness": 0.2,
                "radiometric_delta": 0.1,
            }
        ],
        source_image_id="IMG_PHASE2_002",
        source_uri="fixtures://satim/phase2/IMG_PHASE2_002.png",
        capture_datetime_utc="2026-07-01T00:00:00Z",
        aoi_id="PR_TILE_SEAM_CONTROL",
    )

    assert rows == []
