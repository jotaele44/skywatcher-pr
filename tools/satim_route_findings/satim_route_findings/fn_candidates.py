"""Candidate route-network summaries from SATIM graph ledgers."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .util import safe_float, stable_id


def build_fn_candidate_summary(
    graph_nodes: tuple[dict[str, str], ...],
    graph_edges: tuple[dict[str, str], ...],
) -> list[dict[str, object]]:
    """Build deterministic candidate summaries from track-to-vertex graph links."""

    node_by_id = {row.get("node_id", ""): row for row in graph_nodes if row.get("node_id")}
    vertices_by_track: dict[str, set[str]] = defaultdict(set)
    for edge in graph_edges:
        if edge.get("edge_type", "") != "HAS_VERTEX":
            continue
        source = edge.get("source", "")
        target = edge.get("target", "")
        if source and target:
            vertices_by_track[source].add(target)

    candidates: list[dict[str, object]] = []
    for track_node_id, vertices in vertices_by_track.items():
        track_node = node_by_id.get(track_node_id, {})
        source_name = track_node.get("source", "")
        track_confidence = safe_float(track_node.get("confidence"))
        vertex_confidences = [safe_float(node_by_id.get(vertex, {}).get("confidence")) for vertex in vertices]
        all_confidences = [track_confidence, *vertex_confidences]
        candidates.append(
            {
                "fn_candidate_id": stable_id("fn", source_name, track_node_id, len(vertices)),
                "track_node_id": track_node_id,
                "source": source_name,
                "label": track_node.get("label", ""),
                "vertex_count": len(vertices),
                "confidence_avg": round(mean(all_confidences), 3) if all_confidences else 0.0,
                "confidence_min": round(min(all_confidences), 3) if all_confidences else 0.0,
                "confidence_max": round(max(all_confidences), 3) if all_confidences else 0.0,
            }
        )
    return sorted(candidates, key=lambda row: (str(row["source"]), str(row["track_node_id"])))
