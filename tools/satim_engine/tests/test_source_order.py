import pandas as pd
from satim_engine.graph import build_graph_from_ledgers


def test_graph_ids_match_when_input_rows_are_reordered():
    df1 = pd.DataFrame([
        {"source":"b.csv", "latitude":18.2, "longitude":-66.2, "timestamp":"2026-01-01T00:00:00Z", "verification_score":90},
        {"source":"a.csv", "latitude":18.1, "longitude":-66.1, "timestamp":"2026-01-01T00:00:00Z", "verification_score":90},
    ])
    df2 = df1.iloc[::-1].reset_index(drop=True)
    n1, _ = build_graph_from_ledgers(df1)
    n2, _ = build_graph_from_ledgers(df2)
    assert sorted(n1.node_id.tolist()) == sorted(n2.node_id.tolist())
