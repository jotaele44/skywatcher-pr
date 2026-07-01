from __future__ import annotations
import hashlib
import pandas as pd

def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"

def build_graph_from_ledgers(tracks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes, edges = [], []
    for src, g in tracks.groupby("source", dropna=False, sort=True):
        tid = stable_id("track", src)
        nodes.append({"node_id": tid, "node_type": "TRACK", "label": str(src), "confidence": float(g.get("verification_score", pd.Series([0])).mean()), "source": str(src)})
        source_points = g.head(200).reset_index(drop=True)
        for ordinal, r in source_points.iterrows():
            vertex_key = (src, ordinal, r.get("latitude"), r.get("longitude"), r.get("timestamp"))
            vid = stable_id("vertex", *vertex_key)
            nodes.append({"node_id": vid, "node_type": "VERTEX", "label": f"{r.get('latitude')},{r.get('longitude')}", "confidence": r.get("verification_score", 0), "source": str(src)})
            edges.append({"source": tid, "target": vid, "edge_type": "HAS_VERTEX", "weight": 1.0, "provenance": "track_parse"})
    return pd.DataFrame(nodes), pd.DataFrame(edges)
