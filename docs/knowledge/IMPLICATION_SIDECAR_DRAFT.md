# Cumulative implication sidecar v0.1 — integration HOLD

**Status:** Draft-only; inactive.  
**Original pinned parent:** `b9b1491c7662532476c053f404d422848c4f63e9`.  
**Reconciled main:** `a43b730e2db58cd7a459b15a789eb690122021bc` (PITIRRE AIR | LAND | WATER | SPACE foundation).  
**Scope:** Additive sidecar schema, deterministic Core primitives, and certification tests. There is **no** normal-startup database hook, migration 0004 registration, operational ingestion, API/GUI consumer, MFL rewrite, or production certification.

## Repo-grounded contracts

Skywatcher's authoritative Master Flight Log snapshot store remains `schemas/flight_corpus.sql` plus `src/skywatcher/fr24/flight_corpus.py`. The analytical `flights` table, MFL corpus records, and RLSM-local `screenshots` keep distinct identity scopes. The `swk_*` sidecar records provenance-bound subjects and implications; it does not create another canonical flight history.

Normative ownership follows ontology v2.0 as amended by active v2.1, while the reconciled PITIRRE foundation supplies a separate physical-domain axis: `AIR | LAND | WATER | SPACE`. Analytical ownership (`CORE | RLSM | FPIM | SATIM | CORRIM`) is explicitly separate from physical domain scope. ROAD remains `LAND.TRANSPORT.ROAD`, not a fifth top-level domain. T1–T4 evidence tier and V0–V4 visibility remain independent. A screenshot plus file can be multi-source support only after same-event binding; it is not T5 and never increments the canonical event denominator by itself.

## Draft implementation

- `schemas/knowledge_implications_v1.sql`: 12 prefixed sidecar tables and 10 safety triggers. It is deliberately absent from `MIGRATIONS`.
- `src/skywatcher/core/knowledge_implications.py`: canonical serialization/hashing, bounded denominator delta logic, structured verbal rendering, and explicit recursive stale invalidation for implications directly or transitively dependent on displaced source artifacts.
- `tests/test_knowledge_implications_contract.py`: 21 positive/negative contract gates, including PITIRRE physical-domain scope validation and the FR24 image-skill handoff lock.
- `tests/test_knowledge_implications_migration_gate.py`: 5 migration-atomicity gates, including the unsafe unwrapped-`executescript` negative control and prospective 0004 schema-version receipt rollback/commit tests.
- `tests/test_knowledge_implications_existing_db_integration.py`: 4 representative integration gates against released 0001 and 0003 database states.
- `skills/skywatcher-fr24-image-analysis/SKILL.md`: existing skill upgraded with an activation-gated cumulative implication handoff; the stage must report `NOT_ENABLED` until sidecar activation gates close.
- `.federation/gui-capabilities.json`: one explicit expiring draft exception for the internal Core module/symbols; this does not claim GUI parity for an inactive capability.
- `docs/SKILL_UPGRADE_CANDIDATE.md`: proposed, uninstalled operational skill amendment.

## Hardened invariants

The draft now fails closed on malformed canonical hashes, unconstrained knowledge-delta vocabulary, invalid or duplicate PITIRRE physical-domain scopes, physical-domain/scope-mode cardinality mismatches, knowledge-state self-parenting, direct/transitive implication-lineage cycles, mutation of lineage edges, removal/rewrite of the last support for a PASS implication, mutation of certified implication content, and use of stale/invalid implications as current verbal output.

Source-byte identity, source namespace identity, subject identity, and canonical event identity remain separate. Near-duplicate/discovery-key collisions are preserved as separate candidate artifacts. Contradictory support/counterevidence is retained rather than resolved by overwrite.

When a source dependency is explicitly displaced, `invalidate_implications_for_artifacts()` walks descendant lineage and marks all current/recomputed affected implications `STALE`, reopening their certification. It does not infer replacements or recompute a conclusion automatically.

## Migration certification boundary

The integration suite creates isolated temporary databases using the repository's actual migration framework:

1. **0001 → sidecar**: populate representative batch/screenshot/aircraft/flight/link rows; apply sidecar; assert old-table row conservation, schema-version conservation, FK integrity, and repeatable sidecar application.
2. **0003 → sidecar**: persist a representative MFL snapshot through `persist_corpus_snapshot()`; apply sidecar; assert MFL records/manifestations and schema version are unchanged.
3. Exercise a bounded MFL/screenshot review association without creating a canonical-event count.
4. Preserve two same-discovery-key/different-byte artifacts plus SUPPORT and COUNTEREVIDENCE and an unresolved IDENTITY contradiction.
5. Verify the sidecar exposes no mission/intent/purpose output field.
6. Inject a DDL failure and prove explicit transaction rollback removes every `swk_*` object; the negative control proves naive unwrapped `sqlite3.executescript()` is not atomic.

These are representative repository fixtures, **not the operator-local corpus** and not a certification of all historical databases.

## Pre-activation gates

| Gate | State |
|---|---|
| Main-parent / branch-drift check | PASS — merge commit reconciles current PITIRRE foundation main; recheck if main moves again |
| Repository CI / lint / frontend / CodeQL / federation gates | Must PASS on final commit |
| 0001 and 0003 isolated compatibility tests | Implemented; final CI must PASS |
| Deliberate DDL-failure rollback | Implemented; final CI must PASS |
| Hash/delta/lineage/stale-invalidation hardening | Implemented; final CI must PASS |
| Genuine operator-corpus screenshot ↔ MFL adjudication | **BLOCKED — corpus is machine-local** |
| Operator-local full RLSM replay and gold sample | **BLOCKED — external to GitHub CI** |
| Exact prospective 0004 migration-ledger atomicity | Implemented; final CI must PASS |
| Migration 0004 registration | **BLOCKED** until operator-corpus gates close; registration itself remains intentionally absent |
| Active ingestion/API/GUI wiring | **BLOCKED** |
| Production/whole-repository certification | **BLOCKED** |

A synthetic or representative PASS cannot be promoted to operator-corpus or production certification.

**No automatic merge. No force push. No migration registration. No production certification.**
