# Skywatcher v0.4 — Phase 0 repository reconciliation

**Status:** Proposed integration contract; no production analytical behavior changed.
**Baseline:** `main`, tree `770517f42fdd8aa90b89faebf3069795e564913b` (inspected 2026-10-23).
**Source proposals:** Local analytical architecture v0.2 and controlled terminology v0.3.
**Canonical ILAP expansion:** **(Potential) In-Land Access Point**.

## Existing implementation — do not duplicate

- `src/skywatcher/evidence_router.py` and `docs/SKYWATCHER_EVIDENCE_INGESTION_CONTRACT.md`: governing evidence routing, manifestation identity, and fail-closed certification.
- `src/skywatcher/corrim/ilap_airspace_bridge.py` via root compatibility shim `ilap_airspace_bridge.py`: existing ILAP/airspace interface.
- `fr24/`, `data/flight_tracks/`, `config/flight_corpus_v4.json`: flight data and established analytics contracts.
- `src/skywatcher/satim/`, `docs/SKYWATCHER_DATABASE_SCHEMA.md`: imagery/ground analysis and data models.
- `frontend/src/components/skywatcher/`: existing user-facing workflows.
- `.github/workflows/ci.yml`, `.federation/gui-capabilities.json`, `AGENTS.md`: existing quality and GUI parity requirements.

## Vocabulary reconciliation (normative)

The governing ingestion contract uses evidence states:
`FACT`, `COMPUTED`, `BINDING`, `INFERENCE`, `ASSUMPTION`, `HYPOTHESIS`, `UNKNOWN`.

Its certification states are:
`PASS`, `FAIL`, `OPEN`, `BLOCKED`, `PROVISIONAL`, `AUDIT_ONLY`, `NONCANONICAL`, `CANDIDATE_NOT_IDENTITY`, `UNRESOLVED`, `SUPERSEDED`.

The proposed v0.3 glossary's `OBSERVED`, `DERIVED`, `INFERRED`, `HYPOTHESIZED` and `VERIFIED`, `REJECTED` are **display/interpretive aliases only** pending an explicit, tested crosswalk. Do not replace stored enums or infer one-to-one certification equivalence. In particular `DERIVED` is not necessarily certified `COMPUTED`; `VERIFIED` is not automatically `PASS`.

ILAP evidence level, infrastructure documentation status, investigative priority, and SARP disposition are independent attributes. ILAP levels v0.3 remain **proposed**; do not migrate existing ILAP identifiers or level values without a documented mapping and backwards-compatible schema plan.

## Implementation order and gates

1. **Inventory and baseline:** Record exact existing interfaces, fixtures, database migrations, GUI routes, and source identity contracts; generate a collision report before edits.
2. **Terminology crosswalk:** Define versioned, non-destructive mappings to existing enum and API fields; preserve raw values and historical records.
3. **Evidence core:** Extend existing router and provenance ledger, not a parallel ingestion pipeline. Require byte hashes, manifestation inventory, idempotence, and fail-closed arithmetic closure.
4. **Flight analytics:** Extend existing FR24/corpus modules; ensure rendered trail is never promoted to raw trajectory, and reporting gaps never imply suppression.
5. **GTC-S and ILAP:** Add only bounded, independently corroborated correlation and infrastructure context; no automated discovery or disclosure of undisclosed restricted access points.
6. **SARP:** Enforce access and publication review before candidate export. Unknown designation is not classified/covert status.
7. **GUI parity:** Any user-facing capability must follow backend → API/IPC → state → GUI → discoverable workflow, with corresponding updates to `.federation/gui-capabilities.json` and end-to-end tests.
8. **Certification and rollout:** Validate source contracts and regression fixtures, run `python scripts/check_gui_parity.py` and frontend `npm run test:gui-parity`, then review PR before merge.

## Stop conditions

- No silent renaming of governing evidence/certification states.
- No replacement of source records or canonical baseline artifacts.
- No automated ILAP promotion from screenshot geometry, mere aircraft proximity, data gaps, or geological suitability.
- No claim of classified/covert status without authoritative documentation.
- No public release of sensitive location details without human approval.
- No claim of test completion until commands actually run in a checkout/CI.

## Phase 0 exit criteria

- [x] Live repository and default branch identified.
- [x] Existing governing ingestion contract inspected.
- [x] Existing ILAP bridge and Python packaging inspected.
- [x] GUI parity protocol identified.
- [x] Reconciliation specification added on an isolated feature branch.
- [ ] Full source/schema/fixture compatibility matrix.
- [ ] Terminology crosswalk approved.
- [ ] Existing CI and GUI parity tests run against integration changes.
- [ ] Production module changes reviewed and merged.

**Scope of this PR:** Documentation-only Phase 0; it does not activate autonomous ingestion, alter ILAP classifications, or deploy a new pipeline.
