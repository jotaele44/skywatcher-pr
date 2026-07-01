from __future__ import annotations
import hashlib
import pandas as pd

def _stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"

def build_graph_from_ledgers(tracks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes, edges = [], []
    for src, g in tracks.groupby("source", dropna=False):
        tid = _stable_id("track", src)
        nodes.append({"node_id": tid, "node_type": "TRACK", "label": str(src), "confidence": float(g.get("verification_score", pd.Series([0])).mean()), "source": str(src)})
        for i, r in g.head(200).iterrows():
            vid = _stable_id("vertex", src, i, r.get("latitude"), r.get("longitude"))
            nodes.append({"node_id": vid, "node_type": "VERTEX", "label": f"{r.get('latitude')},{r.get('longitude')}", "confidence": r.get("verification_score", 0), "source": str(src)})
            edges.append({"source": tid, "target": vid, "edge_type": "HAS_VERTEX", "weight": 1.0, "provenance": "track_parse"})
    return pd.DataFrame(nodes), pd.DataFrame(edges)
