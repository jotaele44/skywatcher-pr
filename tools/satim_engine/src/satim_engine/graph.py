from __future__ import annotations
import pandas as pd

def build_graph_from_ledgers(tracks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes, edges = [], []
    for src, g in tracks.groupby("source", dropna=False):
        tid = f"track:{abs(hash(src)) % 10**10}"
        nodes.append({"node_id": tid, "node_type": "TRACK", "label": str(src), "confidence": float(g.get("verification_score", pd.Series([0])).mean()), "source": str(src)})
        for i, r in g.head(200).iterrows():
            vid = f"vertex:{abs(hash((src, i))) % 10**12}"
            nodes.append({"node_id": vid, "node_type": "VERTEX", "label": f"{r.get('latitude')},{r.get('longitude')}", "confidence": r.get("verification_score", 0), "source": str(src)})
            edges.append({"source": tid, "target": vid, "edge_type": "HAS_VERTEX", "weight": 1.0, "provenance": "track_parse"})
    return pd.DataFrame(nodes), pd.DataFrame(edges)
