from __future__ import annotations
import hashlib
import pandas as pd

def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"

def build_graph_from_ledgers(tracks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes, edges = [], []
    for src, group in tracks.groupby("source", dropna=False, sort=True):
        track_id = stable_id("track", src)
        nodes.append({"node_id": track_id, "node_type": "TRACK", "label": str(src), "confidence": float(group.get("verification_score", pd.Series([0])).mean()), "source": str(src)})
        rows = group.head(200).reset_index(drop=True)
        for ordinal, row in rows.iterrows():
            point_id = stable_id("vertex", src, ordinal, row.get("latitude"), row.get("longitude"), row.get("timestamp"))
            nodes.append({"node_id": point_id, "node_type": "VERTEX", "label": f"{row.get('latitude')},{row.get('longitude')}", "confidence": row.get("verification_score", 0), "source": str(src)})
            edges.append({"source": track_id, "target": point_id, "edge_type": "HAS_VERTEX", "weight": 1.0, "provenance": "track_parse"})
    return pd.DataFrame(nodes), pd.DataFrame(edges)
