"""Confidence scoring for GATIM review rows."""
from __future__ import annotations


def score_candidate(row) -> float:
    score = 0.25
    if row.coord_status == "direct":
        score += 0.30
    if row.url:
        score += 0.10
    if row.note or row.tags:
        score += 0.10
    if row.dedupe_cluster_size and row.dedupe_cluster_size.isdigit() and int(row.dedupe_cluster_size) > 1:
        score += 0.10
    if row.visual_features and row.visual_features != "unspecified":
        score += 0.10
    return min(score, 0.95)
