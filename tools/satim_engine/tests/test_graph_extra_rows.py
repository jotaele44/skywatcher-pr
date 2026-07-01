import pandas as pd
from satim_engine.graph import build_graph_from_ledgers


def test_same_source_edges_match_with_extra_rows():
    rows = pd.DataFrame([
        {"source":"case.csv", "latitude":18.1, "longitude":-66.1, "timestamp":"2026-01-01T00:00:00Z", "verification_score":95}
    ])
    rows2 = pd.concat([
        pd.DataFrame([{"source":"other.csv", "latitude":18.0, "longitude":-66.0, "timestamp":"2026-01-01T00:00:00Z", "verification_score":80}]),
        rows,
    ], ignore_index=True)
    n1, e1 = build_graph_from_ledgers(rows)
    n2, e2 = build_graph_from_ledgers(rows2)
    track = n1[n1.label == "case.csv"].node_id.iloc[0]
    assert e1[e1.source == track].target.tolist() == e2[e2.source == track].target.tolist()
