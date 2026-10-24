# Skill upgrade candidate — Skywatcher provenance-bound cumulative implication

**State:** APPLIED_TO_EXISTING_FR24_IMAGE_SKILL_ON_DRAFT_BRANCH; NOT_MERGED. Operator-corpus validation and sidecar activation remain blocked; the exact read-only local certification procedure is now implemented under `docs/knowledge/OPERATOR_CORPUS_CERTIFICATION_RUNBOOK.md`.

The existing `skills/skywatcher-fr24-image-analysis/SKILL.md` now carries an activation-gated cumulative implication handoff. The upgrade is reconciled with the PITIRRE `AIR | LAND | WATER | SPACE` foundation without rewriting historical SkyWatcher provenance. The following gates are the broader workflow upgrade:

1. Parse raw source and preserve every manifestation before event adjudication. Namespace external keys by source system/database and frozen source manifestation.
2. Never derive event, airframe, operator, mission, site, or facility identity from name only, registration only, count equality, hash equality, nearest-only, proximity-only, same-category, or source absence.
3. Separate V0 observations, V1 computed features, independently adjudicated identity, FPIM interpretation, SATIM interpretation, and CORRIM cross-domain association.
4. Respect active v2.1 evidence axes: T1–T4 tier, V0–V4 visibility, provenance, availability, geometry, temporal precision, review state, confidence, and priority remain orthogonal. Screenshot+track support is not T5 and never increments an event denominator without same-event binding.
5. Every implication must carry a typed implication class, **analysis owner** and separately validated **physical-domain scope**, support/counterevidence/control roles, ruleset version, and dependency hash. Analytical ownership is not a physical domain. Hypotheses cannot become independent evidence for themselves.
6. Report an explicit knowledge delta after adjudication or `NO_MATERIAL_CHANGE`. Source-manifestation growth and canonical-event growth are separate counters.
7. A changed/displaced dependency must recursively stale every affected implication descendant before any result can be rendered current. Frozen prior states remain auditable.
8. Implication lineage must be acyclic and immutable. Tied or cyclic top evidence remains unresolved; deterministic graph traversal is not evidentiary support.
9. Independent denominator changes require frozen lineage/continuity evidence. Different hashes prove byte difference only; identical frozen bytes with inconsistent counts create a contradiction.
10. Preserve contradictory evidence as first-class state. Do not resolve near-duplicates, conflicting identity candidates, or same-discovery-key records by overwrite.
11. Verbal output may render only current/recomputed structured state; it may not invent evidence, purpose, intent, coordination, wrongdoing, subsurface relevance, or mission from geometry/recurrence.
12. Any SQLite schema extension must have a positive explicit-transaction rollback fixture and a negative unwrapped-`executescript` fixture before migration registration.
13. Migration compatibility must test released database states for schema-version conservation, existing-row conservation, FK integrity, idempotence, and no event multiplication.
14. Repository CI/synthetic fixtures do not certify an operator-local corpus. Require operator replay and independently reviewed gold/identity evidence before enabling normal-startup migration, active consumers, or production certification.
15. Operator screenshot↔MFL certification must be bounded to an explicitly frozen candidate denominator. Current v0.1 discovery is exhaustive only within the independently reviewed gold-300 frames and exact case-folded callsign/registration-folder rules; it is not universal flight-link discovery.
16. SAME_EVENT requires at least one independent strong binding basis plus an evidence reference; DIFFERENT_EVENT requires independent exclusion/contradiction evidence. DISPLAYED_SOURCE_FLIGHT_ID, CALLSIGN_ONLY, REGISTRATION_ONLY, SPATIAL_PROXIMITY, and NEAREST_TIME cannot close identity by themselves.
17. Operator certification writes reviewed relations into a separate scratch sidecar only. RLSM, MFL, canonical event counts, and migration 0004 remain unchanged until a later explicit activation decision.
