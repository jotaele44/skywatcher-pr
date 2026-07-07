"""Contradiction review helpers for GATIM rows."""
from __future__ import annotations


def contradiction_flags(row) -> list[str]:
    flags = []
    if row.coord_status != "direct":
        flags.append("coord_unresolved")
    if not row.note and not row.tags:
        flags.append("sparse_context")
    if not row.visual_features or row.visual_features == "unspecified":
        flags.append("ordinary_feature_check_needed")
    if row.dedupe_cluster_size and row.dedupe_cluster_size.isdigit() and int(row.dedupe_cluster_size) > 1:
        flags.append("duplicate_or_repeat_pin")
    if row.class_primary == "UAP_CASE_ANCHOR":
        flags.append("context_anchor_not_site_claim")
    return flags


def contradiction_summary(row) -> str:
    flags = contradiction_flags(row)
    return ";".join(flags) if flags else "no_initial_contradiction_flag"
