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


def test_vertex_ids_ignore_global_dataframe_index_shift():
    base = pd.DataFrame([
        {"source":"a.csv", "latitude":18.1, "longitude":-66.1, "timestamp":"2026-01-01T00:00:00Z", "verification_score":95}
    ])
    shifted = pd.concat([
        pd.DataFrame([{"source":"z.csv", "latitude":17.9, "longitude":-65.9, "timestamp":"2026-01-01T00:00:00Z", "verification_score":80}]),
        base,
    ], ignore_index=True)
    _, e_base = build_graph_from_ledgers(base)
    _, e_shifted = build_graph_from_ledgers(shifted)
    base_vertex = e_base.loc[e_base.source.str.startswith("track:"), "target"].iloc[0]
    shifted_vertex = e_shifted[e_shifted["source"] == e_base.iloc[0].source]["target"].iloc[0]
    assert base_vertex == shifted_vertex
