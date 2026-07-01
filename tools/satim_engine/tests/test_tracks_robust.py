from pathlib import Path
import pandas as pd
import pytest
from satim_engine.tracks import parse_csv_track, NonTrackCSV

def test_parse_lat_lon_aliases(tmp_path):
    f = tmp_path / "track.csv"
    f.write_text("Y,X,velocity\n18.1,-66.1,120\n")
    df = parse_csv_track(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == 18.1

def test_nontrack_csv_is_classified(tmp_path):
    f = tmp_path / "not_track.csv"
    f.write_text("name,value\na,1\n")
    with pytest.raises(NonTrackCSV):
        parse_csv_track(str(f))
