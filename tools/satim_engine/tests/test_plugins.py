import pandas as pd
from satim_engine.plugins.visual_ocr import extract_visual_metadata
from satim_engine.plugins.gis_join import bbox_context_join

def test_extract_visual_metadata_uses_filename_fallback():
    meta = extract_visual_metadata("/tmp/screenshots/FR24_TEST1_2026-01-01.jpg")
    assert meta["ocr_status"] == "FILENAME_ONLY"
    assert meta["text"] == "FR24_TEST1_2026-01-01"
    assert meta["plugin"] == "visual_ocr.default_filename_adapter"
    assert meta["callsign_hint"] is None
    assert meta["timestamp_hint"] is None
    assert meta["tail_hint"] is None

def test_bbox_context_join_empty_track_df():
    empty = pd.DataFrame(columns=["source", "latitude", "longitude"])
    out = bbox_context_join(empty)
    assert list(out.columns) == ["source", "latitude", "longitude", "gis_join_status"]
    assert out.empty

def test_bbox_context_join_stamps_status_with_no_layers():
    df = pd.DataFrame([{"source": "track.csv", "latitude": 18.1, "longitude": -66.1}])
    out = bbox_context_join(df)
    assert out.loc[0, "gis_join_status"] == "BBOX_CONTEXT_ONLY"
    assert out.loc[0, "gis_layer_count"] == 0

def test_bbox_context_join_preserves_baseline_column_order():
    # The context-only path feeds the committed production baseline SHA, so its
    # header must stay source,latitude,longitude,gis_join_status,gis_layer_count.
    df = pd.DataFrame([{"source": "track.csv", "latitude": 18.1, "longitude": -66.1}])
    out = bbox_context_join(df)
    assert list(out.columns) == [
        "source", "latitude", "longitude", "gis_join_status", "gis_layer_count"
    ]

def test_bbox_context_join_counts_supplied_layers():
    df = pd.DataFrame([{"source": "track.csv", "latitude": 18.1, "longitude": -66.1}])
    out = bbox_context_join(df, layers={"parcels": object(), "roads": object()})
    assert out.loc[0, "gis_layer_count"] == 2

def test_bbox_context_join_never_mutates_input():
    df = pd.DataFrame([{"source": "track.csv", "latitude": 18.1, "longitude": -66.1}])
    original = df.copy()
    bbox_context_join(df)
    pd.testing.assert_frame_equal(df, original)
