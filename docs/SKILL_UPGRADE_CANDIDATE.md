# Skill upgrade candidate — Skywatcher provenance-bound cumulative implication

**State:** CANDIDATE_NOT_INSTALLED (repository-tested draft; operator-corpus validation still blocked).

New mandated gates for screenshot/flight ingestion analysis:

1. Parse raw source and preserve every manifestation before event adjudication. Namespace external keys by source system/database and frozen source manifestation.
2. Never derive event, airframe, operator, mission, site, or facility identity from name only, registration only, count equality, hash equality, nearest-only, proximity-only, same-category, or source absence.
3. Separate V0 observations, V1 computed features, independently adjudicated identity, FPIM interpretation, SATIM interpretation, and CORRIM cross-domain association.
4. Respect active v2.1 evidence axes: T1–T4 tier, V0–V4 visibility, provenance, availability, geometry, temporal precision, review state, confidence, and priority remain orthogonal. Screenshot+track support is not T5 and never increments an event denominator without same-event binding.
5. Every implication must carry a typed implication class, owning domain, support/counterevidence/control roles, scope, ruleset version, and dependency hash. Hypotheses cannot become independent evidence for themselves.
6. Report an explicit knowledge delta after adjudication or `NO_MATERIAL_CHANGE`. Source-manifestation growth and canonical-event growth are separate counters.
7. A changed/displaced dependency must recursively stale every affected implication descendant before any result can be rendered current. Frozen prior states remain auditable.
8. Implication lineage must be acyclic and immutable. Tied or cyclic top evidence remains unresolved; deterministic graph traversal is not evidentiary support.
9. Independent denominator changes require frozen lineage/continuity evidence. Different hashes prove byte difference only; identical frozen bytes with inconsistent counts create a contradiction.
10. Preserve contradictory evidence as first-class state. Do not resolve near-duplicates, conflicting identity candidates, or same-discovery-key records by overwrite.
11. Verbal output may render only current/recomputed structured state; it may not invent evidence, purpose, intent, coordination, wrongdoing, subsurface relevance, or mission from geometry/recurrence.
12. Any SQLite schema extension must have a positive explicit-transaction rollback fixture and a negative unwrapped-`executescript` fixture before migration registration.
13. Migration compatibility must test released database states for schema-version conservation, existing-row conservation, FK integrity, idempotence, and no event multiplication.
14. Repository CI/synthetic fixtures do not certify an operator-local corpus. Require operator replay and independently reviewed gold/identity evidence before enabling normal-startup migration, active consumers, or production certification.
