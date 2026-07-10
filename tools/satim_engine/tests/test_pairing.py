import pandas as pd
from satim_engine.pairing import build_pairing_ledger
from satim_engine.schema import PAIRING_COLUMNS

CONFIG = {
    "pairing": {
        "time_window_minutes": 30,
        "spatial_threshold_meters": 1500,
        "confidence_threshold_promote": 80,
    }
}


def _tracks():
    return pd.DataFrame([
        {"source": "flight_a.csv", "timestamp": "2026-01-01T12:00:00Z", "latitude": 18.1, "longitude": -66.1, "verification_score": 95},
        {"source": "flight_a.csv", "timestamp": "2026-01-01T12:05:00Z", "latitude": 18.11, "longitude": -66.11, "verification_score": 95},
        {"source": "flight_b.csv", "timestamp": "2026-01-01T09:00:00Z", "latitude": 18.5, "longitude": -66.5, "verification_score": 40},
    ])


def test_pairing_columns_match_schema():
    out = build_pairing_ledger(pd.DataFrame(), [], CONFIG)
    assert list(out.columns) == PAIRING_COLUMNS


def test_match_within_window_is_promoted_when_confidence_clears_threshold():
    visual_rows = [{"visual_path": "photo1.jpg", "timestamp_hint": "2026-01-01T12:02:00Z"}]
    out = build_pairing_ledger(_tracks(), visual_rows, CONFIG)

    matched = out[out["track_file"] == "flight_a.csv"]
    assert len(matched) == 1
    row = matched.iloc[0]
    assert row["match_basis"] == "TIMESTAMP_WITHIN_WINDOW"
    assert row["status"] == "PROMOTED"
    assert row["confidence"] >= CONFIG["pairing"]["confidence_threshold_promote"]
    assert "flight_b.csv" not in out["track_file"].values


def test_match_outside_window_is_unmatched():
    visual_rows = [{"visual_path": "photo2.jpg", "timestamp_hint": "2026-01-01T23:00:00Z"}]
    out = build_pairing_ledger(_tracks(), visual_rows, CONFIG)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["match_basis"] == "NO_TRACK_IN_WINDOW"
    assert row["status"] == "UNMATCHED"
    assert row["confidence"] == 0.0
    assert row["track_file"] == ""


def test_missing_timestamp_hint_is_unmatched():
    visual_rows = [{"visual_path": "photo3.jpg", "timestamp_hint": None}]
    out = build_pairing_ledger(_tracks(), visual_rows, CONFIG)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["match_basis"] == "NO_TIMESTAMP_HINT"
    assert row["status"] == "UNMATCHED"
    assert row["confidence"] == 0.0


def test_low_confidence_match_is_candidate_not_promoted():
    visual_rows = [{"visual_path": "photo4.jpg", "timestamp_hint": "2026-01-01T09:20:00Z"}]
    out = build_pairing_ledger(_tracks(), visual_rows, CONFIG)

    matched = out[out["track_file"] == "flight_b.csv"]
    assert len(matched) == 1
    row = matched.iloc[0]
    assert row["match_basis"] == "TIMESTAMP_WITHIN_WINDOW"
    assert row["status"] == "CANDIDATE"
    assert row["confidence"] < CONFIG["pairing"]["confidence_threshold_promote"]


def test_tracks_without_timestamp_column_do_not_crash():
    # cli.run() drops all-NA columns, so a KML/GPX-only batch can reach pairing
    # with a `source` column but no `timestamp` column at all.
    tracks = pd.DataFrame([
        {"source": "route.kml", "latitude": 18.1, "longitude": -66.1, "verification_score": 30},
    ])
    assert "timestamp" not in tracks.columns
    visual_rows = [{"visual_path": "photo.jpg", "timestamp_hint": "2026-01-01T12:00:00Z"}]
    out = build_pairing_ledger(tracks, visual_rows, CONFIG)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["match_basis"] == "NO_TRACK_IN_WINDOW"
    assert row["status"] == "UNMATCHED"


def test_pair_id_is_deterministic():
    visual_rows = [{"visual_path": "photo1.jpg", "timestamp_hint": "2026-01-01T12:02:00Z"}]
    out1 = build_pairing_ledger(_tracks(), visual_rows, CONFIG)
    out2 = build_pairing_ledger(_tracks(), visual_rows, CONFIG)
    assert out1["pair_id"].tolist() == out2["pair_id"].tolist()
