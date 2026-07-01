import pandas as pd
from satim_engine.scoring import score_tracks

def test_score_tracks_verifiedish():
    df = pd.DataFrame([{"timestamp":"2026-01-01", "latitude":18.1, "longitude":-66.1, "altitude":1000, "speed":120, "callsign":"TEST"}])
    out = score_tracks(df)
    assert out.loc[0, "verification_score"] >= 90
