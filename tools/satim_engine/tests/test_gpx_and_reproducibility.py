from pathlib import Path
import pandas as pd
from satim_engine.tracks import parse_gpx_coordinates
from satim_engine.graph import build_graph_from_ledgers


def test_parse_gpx_coordinates(tmp_path):
    f = tmp_path / "track.gpx"
    f.write_text('''<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="18.1" lon="-66.1"><ele>12</ele><time>2026-01-01T00:00:00Z</time></trkpt></trkseg></trk></gpx>''')
    df = parse_gpx_coordinates(str(f))
    assert len(df) == 1
    assert float(df.iloc[0].latitude) == 18.1
    assert float(df.iloc[0].longitude) == -66.1


def test_graph_ids_are_stable():
    df = pd.DataFrame([
        {"source":"a.csv", "latitude":18.1, "longitude":-66.1, "timestamp":"2026-01-01T00:00:00Z", "verification_score":95}
    ])
    n1, e1 = build_graph_from_ledgers(df)
    n2, e2 = build_graph_from_ledgers(df)
    assert n1.node_id.tolist() == n2.node_id.tolist()
    assert e1.target.tolist() == e2.target.tolist()
