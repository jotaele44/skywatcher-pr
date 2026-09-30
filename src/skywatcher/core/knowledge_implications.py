"""Pure, offline, deterministic primitives for a provenance-bound KB sidecar.

This module deliberately does not infer event identity, classify mission/intent,
read RLSM's separate database, or update the Master Flight Log.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

COUNTER_KEYS = (
    "source_manifestation_count",
    "unresolved_candidate_count",
    "implication_count",
    "contradiction_count",
)


def canonical_json(obj: Any) -> bytes:
    """Stable UTF-8 serialization; float/NaN handling is fail closed."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_canonical(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def dependency_digest(*, ruleset_version: str,
                      dependencies: Sequence[Mapping[str, str]]) -> str:
    """Hash a deduplicated, sorted support ledger; duplicate edges are errors."""
    if not ruleset_version:
        raise ValueError("ruleset_version is required")
    wanted = ("kind", "id", "version", "role")
    rows: list[tuple[str, ...]] = []
    for edge in dependencies:
        if set(edge) != set(wanted) or any(not isinstance(edge[k], str) or not edge[k] for k in wanted):
            raise ValueError("every dependency requires nonempty kind,id,version,role")
        rows.append(tuple(edge[k] for k in wanted))
    if not rows or len(rows) != len(set(rows)):
        raise ValueError("dependencies must be nonempty and unique")
    return sha256_canonical({"ruleset_version": ruleset_version,
                             "dependencies": sorted(rows)})


def classify_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, int | None]:
    """Counter deltas only: never synthesize a canonical event denominator.

    A canonical event delta is available solely when BOTH states declare the
    same frozen authority lineage. Different denominator manifests are NONCOMPARABLE.
    """
    out: dict[str, int | None] = {}
    for k in COUNTER_KEYS:
        a, b = before.get(k), after.get(k)
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (a, b)):
            raise ValueError(f"invalid conserved counter: {k}")
        out[k] = b - a
    a, b = before.get("canonical_event_count"), after.get("canonical_event_count")
    refs = (before.get("canonical_denominator_ref"), after.get("canonical_denominator_ref"))
    hashes = (before.get("canonical_denominator_sha256"), after.get("canonical_denominator_sha256"))
    lineage = (before.get("denominator_lineage_id"), after.get("denominator_lineage_id"))
    receipts = (before.get("continuity_receipt_sha256"), after.get("continuity_receipt_sha256"))
    if a is not None and b is not None:
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (a,b)):
            raise ValueError("invalid canonical event count")
        if not all(refs) or refs[0] != refs[1]:
            out["canonical_event_count"] = None
            return out
        # Identical frozen denominator bytes with different reported counts
        # constitute a contradiction, not a real delta.
        if hashes[0] and hashes[0] == hashes[1] and a != b:
            raise ValueError("identical denominator source differs in count")
        if (not all(lineage) or lineage[0] != lineage[1]
                or not all(receipts) or receipts[0] != receipts[1]
                or len(receipts[0]) != 64 or not all(hashes)):
            out["canonical_event_count"] = None
        else:
            out["canonical_event_count"] = b - a
    else:
        out["canonical_event_count"] = None
    return out


def deterministic_verbal_output(implication: Mapping[str, Any]) -> str:
    """Only render adjudicated structured data. No freeform invented conclusions."""
    required = ("statement", "epistemic_class", "implication_type", "delta_type",
                "certification_state", "source_refs", "limitations")
    if any(k not in implication for k in required):
        raise ValueError("incomplete implication; cannot render")
    if implication["certification_state"] == "PASS" and not implication["source_refs"]:
        raise ValueError("PASS has no source references")
    if implication.get("validity_state") not in ("CURRENT", "RECOMPUTED"):
        raise ValueError("stale or invalid implication cannot render as current")
    return (f"{implication['epistemic_class']} · {implication['implication_type']}\n"
            f"{implication['statement']}\n"
            f"Knowledge delta: {implication['delta_type']}\n"
            f"Sources: {', '.join(implication['source_refs']) or 'none'}\n"
            f"Limitations: {', '.join(implication['limitations']) or 'none stated'}\n"
            f"Certification: {implication['certification_state']}")
