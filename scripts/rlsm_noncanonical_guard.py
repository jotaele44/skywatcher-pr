#!/usr/bin/env python3
"""Fail-closed quarantine for legacy RLSM analytics.

These analyses remain useful for diagnostics and historical comparison, but
several predate the evidence contracts now required for canonical claims. They
may run only with an explicit ``--audit-only`` acknowledgement, and all outputs
are redirected below ``outputs/audit_noncanonical`` so they cannot silently
replace canonical artifacts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

AUDIT_RULES = {
    "network_graph": [
        "legacy graph falls back to filename_ts",
        "legacy registration may be OCR-only",
        "co-occurrence lacks a closed simultaneous-observation-opportunity denominator",
        "community membership is not coordination evidence",
    ],
    "route_inference": [
        "legacy route timing falls back to filename_ts",
        "legacy registration may be OCR-only",
        "screen-visible labeled POIs are not aircraft visits or endpoints",
        "shared route labels are not coordination evidence",
    ],
    "predictive": [
        "legacy forecast timing falls back to filename_ts",
        "legacy registration may be OCR-only",
        "observation opportunity and coverage are not normalized",
    ],
    "change_detection": [
        "legacy month assignment falls back to filename_ts",
        "legacy registration may be OCR-only",
        "absence is not normalized by observation opportunity or coverage",
    ],
    "spatial_map": [
        "screen-visible POI labels are joined to aircraft visible in the same screenshot",
        "map-label visibility is not aircraft position or municipal footprint",
        "same-screen co-presence is not operational relationship evidence",
    ],
    "cluster_unlabeled_pois": [
        "raw pixel coordinates are compared across screenshots without certified viewport equivalence",
        "recurring pixel position alone is not persistent ground-feature identity",
        "same-screen aircraft counts are descriptive co-occurrence only",
    ],
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def enter_audit_only(
    *,
    analysis: str,
    audit_only: bool,
    repo: Path,
) -> Path | None:
    """Return a quarantined output directory or block canonical execution."""
    reasons = AUDIT_RULES.get(analysis)
    if not reasons:
        raise ValueError(f"unknown noncanonical analysis: {analysis}")
    record = {
        "analysis": analysis,
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY" if audit_only else "BLOCKED",
        "reasons": reasons,
        "generated_at": _now(),
        "canonical_claims_permitted": False,
    }
    if not audit_only:
        print(json.dumps(record, indent=2, sort_keys=True))
        return None

    output_dir = repo / "outputs" / "audit_noncanonical" / analysis
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "NONCANONICAL_AUDIT_MANIFEST.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_dir
