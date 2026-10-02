"""Offline, deterministic primitives for a provenance-bound KB sidecar.

This module deliberately does not infer event identity, classify mission/intent,
read RLSM's separate database, or update the Master Flight Log.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from .domain_registry import TOP_LEVEL_DOMAINS, validate_domain_path

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


def validate_domain_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an exact PITIRRE physical-domain scope without normalization."""
    if not isinstance(scope, Mapping):
        raise ValueError("domain_scope must be an object")
    allowed = {"scope_mode", "domains", "paths"}
    if set(scope) - allowed:
        raise ValueError("domain_scope contains unsupported fields")

    mode = scope.get("scope_mode")
    if mode not in {"PHYSICAL", "CROSS_DOMAIN", "NON_PHYSICAL"}:
        raise ValueError("invalid domain scope_mode")

    domains = scope.get("domains")
    if not isinstance(domains, list) or any(
        not isinstance(value, str) or not value for value in domains
    ):
        raise ValueError("domain_scope.domains must be a list of canonical strings")
    if len(domains) != len(set(domains)):
        raise ValueError("domain_scope.domains must be unique")
    if any(value not in TOP_LEVEL_DOMAINS for value in domains):
        raise ValueError("domain_scope contains unsupported PITIRRE domain")

    if mode == "PHYSICAL" and len(domains) != 1:
        raise ValueError("PHYSICAL scope requires exactly one domain")
    if mode == "CROSS_DOMAIN" and len(domains) < 2:
        raise ValueError("CROSS_DOMAIN scope requires at least two domains")
    if mode == "NON_PHYSICAL" and domains:
        raise ValueError("NON_PHYSICAL scope cannot carry physical domains")

    paths = scope.get("paths", [])
    if not isinstance(paths, list):
        raise ValueError("domain_scope.paths must be a list")
    if mode == "NON_PHYSICAL" and paths:
        raise ValueError("NON_PHYSICAL scope cannot carry domain paths")

    validated_paths: list[dict[str, str | None]] = []
    for path in paths:
        if not isinstance(path, Mapping):
            raise ValueError("each domain path must be an object")
        if set(path) - {"domain", "subdomain", "network_type"}:
            raise ValueError("domain path contains unsupported fields")
        domain = path.get("domain")
        subdomain = path.get("subdomain")
        network_type = path.get("network_type")
        if not isinstance(domain, str) or not domain:
            raise ValueError("domain path requires canonical domain")
        if subdomain is not None and not isinstance(subdomain, str):
            raise ValueError("subdomain must be a string or null")
        if network_type is not None and not isinstance(network_type, str):
            raise ValueError("network_type must be a string or null")
        resolved = validate_domain_path(
            domain,
            subdomain=subdomain,
            network_type=network_type,
        )
        if domains and resolved.domain not in domains:
            raise ValueError("domain path is outside declared domain denominator")
        validated_paths.append(
            {
                "domain": resolved.domain,
                "subdomain": resolved.subdomain,
                "network_type": resolved.network_type,
            }
        )

    return {
        "scope_mode": mode,
        "domains": list(domains),
        "paths": validated_paths,
    }


def deterministic_verbal_output(implication: Mapping[str, Any]) -> str:
    """Only render adjudicated structured data. No freeform invented conclusions."""
    required = (
        "statement",
        "epistemic_class",
        "implication_type",
        "delta_type",
        "certification_state",
        "source_refs",
        "limitations",
        "analysis_owner",
        "domain_scope",
    )
    if any(k not in implication for k in required):
        raise ValueError("incomplete implication; cannot render")
    if implication["certification_state"] == "PASS" and not implication["source_refs"]:
        raise ValueError("PASS has no source references")
    if implication.get("validity_state") not in ("CURRENT", "RECOMPUTED"):
        raise ValueError("stale or invalid implication cannot render as current")
    domain_scope = validate_domain_scope(implication["domain_scope"])
    domain_label = (
        " + ".join(domain_scope["domains"])
        if domain_scope["domains"]
        else domain_scope["scope_mode"]
    )
    return (f"{implication['epistemic_class']} · {implication['implication_type']}\n"
            f"Owner: {implication['analysis_owner']}\n"
            f"Domain scope: {domain_label}\n"
            f"{implication['statement']}\n"
            f"Knowledge delta: {implication['delta_type']}\n"
            f"Sources: {', '.join(implication['source_refs']) or 'none'}\n"
            f"Limitations: {', '.join(implication['limitations']) or 'none stated'}\n"
            f"Certification: {implication['certification_state']}")

def invalidate_implications_for_artifacts(
    conn: sqlite3.Connection,
    artifact_ids: Sequence[str],
) -> list[str]:
    """Mark directly affected implications and all derived descendants STALE.

    The caller owns the surrounding transaction. Nothing is committed here.
    Source artifacts are immutable; this function is invoked when an old
    artifact/dependency is explicitly displaced by newly adjudicated evidence.
    """
    if isinstance(artifact_ids, (str, bytes)):
        raise ValueError("artifact_ids must be a sequence of IDs, not a scalar string")
    ids = tuple(sorted(set(artifact_ids)))
    if not ids or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("artifact_ids must contain one or more nonempty strings")

    placeholders = ",".join("?" for _ in ids)
    roots = [
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT implication_id
            FROM swk_implication_evidence
            WHERE artifact_id IN ({placeholders})
            """,
            ids,
        )
    ]
    if not roots:
        return []

    values_sql = ",".join("(?)" for _ in roots)
    affected = [
        row[0]
        for row in conn.execute(
            f"""
            WITH RECURSIVE affected(id) AS (
              VALUES {values_sql}
              UNION
              SELECT l.implication_id
              FROM swk_implication_lineage l
              JOIN affected a ON l.parent_implication_id = a.id
            )
            SELECT DISTINCT id FROM affected ORDER BY id
            """,
            tuple(roots),
        )
    ]
    affected_placeholders = ",".join("?" for _ in affected)
    conn.execute(
        f"""
        UPDATE swk_implication
        SET validity_state='STALE',
            certification_state=CASE
              WHEN certification_state='SUPERSEDED' THEN certification_state
              ELSE 'OPEN'
            END
        WHERE implication_id IN ({affected_placeholders})
          AND validity_state IN ('CURRENT','RECOMPUTED')
        """,
        tuple(affected),
    )
    return affected

