import pandas as pd
from satim_engine.graph import build_graph_from_ledgers


def _vertex_ids_for_source(edges, nodes, label):
    track_id = nodes[(nodes.node_type == "TRACK") & (nodes.label == label)].node_id.iloc[0]
    return edges[edges.source == track_id].target.tolist()


def test_per_source_vertex_ids_survive_batch_composition_change():
    target = pd.DataFrame([
        {"source":"target.csv", "latitude":18.1, "longitude":-66.1, "timestamp":"2026-01-01T00:00:00Z", "verification_score":95},
        {"source":"target.csv", "latitude":18.2, "longitude":-66.2, "timestamp":"2026-01-01T00:01:00Z", "verification_score":95},
    ])
    with_unrelated = pd.concat([
        pd.DataFrame([{"source":"other.csv", "latitude":17.9, "longitude":-65.9, "timestamp":"2026-01-01T00:00:00Z", "verification_score":80}]),
        target,
    ], ignore_index=True)
    n1, e1 = build_graph_from_ledgers(target)
    n2, e2 = build_graph_from_ledgers(with_unrelated)
    assert _vertex_ids_for_source(e1, n1, "target.csv") == _vertex_ids_for_source(e2, n2, "target.csv")
