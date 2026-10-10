# PITIRRE Repository Map v1 — Contradiction Ledger

**Source snapshot:** `main@2100e6527d49abc302b804d3175feea9ce614eb4`  
**Scope:** contradictions discovered while classifying the complete 1,363-file Git tree.  
**Post-freeze verification basis:** PR #341, code head `b5f8c607c2fa347276cbfe438ba0f8e0dbcf4b8b`.

## PITIRRE-C001

- **Class:** GEOMETRY
- **State:** RESOLVED
- **Source-snapshot path:** `src/skywatcher/normalizers/air_event_normalizer.py`
- **Original observation:** the frozen source implementation used the generic
  `_float` helper with a `0.0` default for latitude/longitude, allowing
  missing geometry to masquerade as the real coordinate `(0,0)`.
- **Repair:** the active branch now parses coordinates independently from
  ordinary numeric fields; preserves raw source coordinate manifestations;
  distinguishes `VALID | MISSING | INVALID`; keeps legitimate numeric zero;
  emits nullable coordinates plus explicit `geometry_status`; and prevents
  unresolved/invalid geometry from entering cross-domain overlap.
- **Regression evidence:** positive zero-coordinate tests, missing/invalid
  coordinate tests, v2 nullable-geometry schema validation, and spatial-overlap
  negative/positive tests all passed in the PR CI Python 3.10/3.11/3.12 matrix.
- **Former migration gate:** `BLOCKED_GEOMETRY_NULL_SEMANTICS`.
- **Current gate:** `GEOMETRY_NULL_SEMANTICS_PASS`.
- **Disposition:** source-snapshot finding retained as historical evidence;
  repaired active implementation may proceed to later migration/parity gates.

## PITIRRE-C002

- **Class:** CLASS / GOVERNANCE
- **State:** RESOLVED
- **Paths adjudicated:** `docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md`,
  `docs/architecture/ADR_SKYWATCHER_ANALYTICAL_ONTOLOGY_v2_1.md`,
  `src/skywatcher/fr24/mission_classification.py`, plus active FPIM, CORRIM,
  evidence-router, federation-export, API-normalization and GUI consumers.
- **Original conflict:** the older July module-boundary revision permitted
  evidence-gated speculative mission classification, whereas active ontology
  v2.1 states that mission or intent inference remains prohibited.
- **Authority adjudication:** active ontology v2.1 controls. The older
  speculative-mission permission is **SUPERSEDED** for current behavior.
- **Repair:** active mission/intent inference is removed from canonical routing
  and outputs; the historical classifier is Legacy-only and fail-closed by
  default; FPIM no longer maps aircraft type to mission; canonical federation
  export emits `mission_classification=null`; CORRIM does not export inferred
  mission; legacy API fields are quarantined as noncanonical source material;
  GUI surfaces do not render `mission_inference`; source/operator-declared
  mission labels remain permitted only as sourced metadata.
- **Regression evidence:** the dedicated PITIRRE-C002 firewall, FPIM tests,
  exporter tests, ILAP tests, source-taxonomy tests, RLSM tests, frontend tests
  and GUI parity/E2E all passed at the verification basis head.
- **Former migration gate:** `NO_MISSION_PROMOTION`.
- **Current gate:** `NO_MISSION_PROMOTION_PASS / LEGACY_QUARANTINE_ENFORCED`.
- **Displaced rule:** July 2026 speculative/evidence-gated mission inference =
  `SUPERSEDED`.

## Verification receipt

At `b5f8c607c2fa347276cbfe438ba0f8e0dbcf4b8b`, the PR checks required for these contradictions
reported PASS, including:

- Skywatcher CI: Python 3.10 / 3.11 / 3.12, frontend, lint, lock, imagery and ADS-B;
- GUI capability parity and GUI reachability E2E;
- Federation Compatibility;
- HAF Contract Gate;
- Admin Control Plane Boundary;
- SATIM Phase 2 Contracts and SATIM Runtime Smoke Tests;
- Secret scan;
- CodeQL;
- desktop builds for Windows, macOS and Ubuntu.

The status update is claim-scoped to C001/C002. It does not certify the entire
PITIRRE migration or authorize repository rename.

## Arithmetic

```text
contradictions = 2
OPEN           = 0
RESOLVED       = 2
displaced_rules_SUPERSEDED = 1
```

The original contradictions remain visible; resolution does not rewrite the
frozen source snapshot.
