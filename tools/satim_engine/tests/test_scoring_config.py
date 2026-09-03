import pandas as pd
from satim_engine.config import load_config
from satim_engine.scoring import provenance_bucket_edges, score_tracks


def test_provenance_bucket_edges_match_config():
    config = load_config()
    edges = provenance_bucket_edges(config)
    assert edges == [0, 59, 79, 94, 100]


def test_provenance_bucket_edges_follow_custom_config():
    config = {"scoring": {"approximate": 50, "high_confidence": 70, "verified": 90}}
    assert provenance_bucket_edges(config) == [0, 49, 69, 89, 100]


def test_score_tracks_uses_config_thresholds():
    # timestamp(35) + lat/lon(30) + altitude(15) + speed(10) = 90, no callsign/registration.
    df = pd.DataFrame([{"timestamp": "2026-01-01", "latitude": 18.1, "longitude": -66.1, "altitude": 1000, "speed": 120}])

    default_config = {"scoring": {"approximate": 60, "high_confidence": 80, "verified": 95}}
    out_default = score_tracks(df, default_config)
    assert out_default.loc[0, "verification_score"] == 90
    assert out_default.loc[0, "provenance_level"] == "HIGH_CONFIDENCE"

    # Same score, but a config that raises the approximate/high_confidence cutoffs
    # reclassifies the same row into a lower bucket - proves the buckets are
    # config-driven rather than hardcoded.
    stricter_config = {"scoring": {"approximate": 90, "high_confidence": 95, "verified": 99}}
    out_stricter = score_tracks(df, stricter_config)
    assert out_stricter.loc[0, "verification_score"] == 90
    assert out_stricter.loc[0, "provenance_level"] == "APPROXIMATE"
