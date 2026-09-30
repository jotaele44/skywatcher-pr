# Cumulative implication sidecar v0.1 — integration HOLD

**Status:** Draft-only; inactive. **Branch parent:** `b9b1491c7662532476c053f404d422848c4f63e9`.  
**Scope:** Three additive prototype files plus synthetic regression gates; no operational ingestion, MFL migration, database initialization hook, CI activation, API integration, or production claim.

## Repo-grounded contracts

Skywatcher's authoritative MFL snapshot store already lives in `schemas/flight_corpus.sql` and `src/skywatcher/fr24/flight_corpus.py`. The analytical `flights` table, MFL corpus records and RLSM-local `screenshots` have distinct identity scopes. This sidecar has separate `swk_*` tables and cannot certify aircraft, flights, or missions by source hash, name, registration, spatial proximity, or equal counts. `swk_subject_ref` records external namespaces and frozen snapshot keys; it does not create another canonical flight history.

Normative ownership follows active ontology v2.0 as amended by v2.1: Core handles provenance/receipts, RLSM source extraction and localization, FPIM flight behavior, SATIM imagery, and CORRIM cross-domain association. `T1`–`T4` evidence classes and `V0`–`V4` source visibility are independent. A bound screenshot plus file is a multi-source support qualifier, not a new tier.

## Files in draft

- `schemas/knowledge_implications_v1.sql`: 12 prefixed sidecar tables and 6 safety triggers. **Deliberately not registered** in `database_migrations.py`; not installed by normal initialization.
- `src/skywatcher/core/knowledge_implications.py`: offline pure digest, bounded counter delta and structured verbal renderer. No MFL write, identity resolution or network access.
- `tests/test_knowledge_implications_contract.py`: 11 synthetic positive/negative gates, including no source-to-event promotion, fail-closed PASS support, immutable provenance and cross-database namespace separation.
- `docs/SKILL_UPGRADE_CANDIDATE.md`: uninstalled operational skill amendment.

## Current evidence

Original local patch: 11/11 synthetic tests PASS (`PYTHONPATH=src pytest -q tests/test_knowledge_implications_contract.py`); original bytes SHA256 verified against local manifest. This validates the isolated prototype only. GitHub CI and operator-local corpus are not available to the earlier detached local run. Existing full repository tests and installed schema migration remain **OPEN**.

## Pre-activation gates (all required)

1. Verify `main` parent SHA and no collision with other active ontology/schema PRs.
2. Run Python focused and complete relevant repository suites plus frontend adapter tests at the exact release commit, including active v2.1 domain-boundary conformance.
3. Create an **isolated temporary** copy of a representative 0003 database. Explicitly test 0001→sidecar and 0003→sidecar, foreign keys, schema collisions, repeat application, row conservation, read-back and no event multiplication.
4. Inject a deliberate DDL failure and prove atomic rollback; `sqlite3.executescript` has implicit transaction considerations. Do not append migration 0004 until this passes and the exact migration path is approved.
5. Review every `swk_*` object for additional immutable provenance/lineage controls, event denominator continuity, type/null/edge-cycle violations, and stale implication invalidation; the current module is a **primitive**, not a complete dependency-graph worker.
6. Test a genuinely adjudicated screenshot↔MFL record pairing, a near-duplicate negative case, contradictory-source persistence, and zero live mission inference. Operator corpus and physical-device certification remain separate.
7. Freeze passing tests and artifact SHA256, then explicitly authorize migration registration, active ingestion, renderer/consumer wiring and any production claim in a subsequent PR.

**No automatic merge. No operational migrations. No production certification.**
