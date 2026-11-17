# FAEI-V1 — Aviation Evidence and Program Relationship Reconciliation

**Status:** DESIGN CANDIDATE / NO PRODUCTION IMPLEMENTATION / CERTIFICATION WITHHELD  
**Authority:** `docs/SKYWATCHER_EVIDENCE_INGESTION_CONTRACT.md` is governing. This document is an additive investigation profile, **not** a second ingestion router.  
**Baseline:** skywatcher-pr `main` at `4def79d5212ff9990e405c65964198401cde9ce0` (2026-11-03 inspection).

## Goal, scope, gates, and exclusions

Goal: trace an aviation observation through original evidence, typed identifiers, historical flight sessions, organizational relationships, contract records, and scope-limited findings while preventing inference promotion.

In scope: historical open-source aircraft/flight and procurement research, screenshots, user-authorized raw track exports, public registries, provenance, contradictions, retrospective spatial analysis, and UAP-report *correlation as a hypothesis only*.

Out of scope for V1: live tracking of sensitive assets, automated targeting, inferred operational bases, restricted-source bypass, speculative mission classification, and public exposure of precise current positions. Retrospective exports must be time-bounded and access-controlled where warranted.

The shipped path requirement from `AGENTS.md` remains mandatory: backend → API → state → discoverable GUI → E2E tests → capability registry. This PR changes no shipped behavior; it MUST NOT be called a deployed capability.

## Pass A — requirement decomposition

| ID | Requirement | Dependency | Mandatory test/oracle | Failure |
|---|---|---|---|---|
| C01 | Preserve source original bytes and manifestation | input | SHA-256 + byte length replay | BLOCKED if missing |
| C02 | Enumerate complete accessible source denominator | C01 | independent count/page/member inventory | OPEN if incomplete |
| C03 | Preserve raw fields, UI timestamp, screenshot time, file metadata separately | C01 | typed extraction comparison | OPEN |
| C04 | Resolve registry/type only with stable IDs and authoritative dated record | C03 | registry ID crosswalk replay | UNRESOLVED on conflict |
| C05 | Preserve repeated callsigns, registration history, M:N assignments | C04 | reused-ID adversarial fixture | REVIEW |
| C06 | Parse UTC offset, event/session chronology and duplicate observations | C03 | independent UTC conversion and session audit | OPEN |
| C07 | Distinguish displayed rendered paths from original telemetry | C03 | original track points or explicit SCREENSHOT_ONLY | NONCANONICAL |
| C08 | Separate registered owner, actual operator, contracting party, and mission | C04 | independent direct linkage to specific aircraft and dates | CANDIDATE_NOT_IDENTITY |
| C09 | Bind geospatial context with CRS/provenance/uncertainty | C07 | Spiderweb authority and geometry replay | UNRESOLVED |
| C10 | Preserve contradictory evidence rather than replace it | all | conflicting identifier/time/mission fixture | OPEN |
| C11 | Independent result replay from frozen sources | C01–C10 | separate reviewer/implementation | BLOCKED |
| C12 | Freeze exact-head receipts and close scoped claims | C01–C11 | manifest + CI + independent review | WITHHELD |

## Pass B — independent coverage challenge

Threat-based second pass, independent of the sequential execution plan:
- Screenshot text could depict application state, not sensor telemetry; image capture time differs from shown event time.
- Aircraft registration, Mode S hex, airframe serial, and callsign have distinct assignment and temporal validity.
- A call sign may identify multiple flights or platforms; seven listed dates do not prove seven distinct sessions.
- Same contractor and aircraft type in a regional government contract do **not** prove an exact-airframe task-order assignment.
- A registered owner is not necessarily operator or mission authority; public registry facts do not prove who controlled a flight.
- A map pixel trail is not coordinate-accurate telemetry, and visual gaps do not certify signal dropout.
- A slow speed or zero ground speed does not prove hover or landing; barometric zero does not prove ground.
- Apparent coincidence with UAP report, vessel, offshore feature, or installation is a candidate association only.
- Source absence cannot establish stealth, secret status, or specific mission intent.
- Contracts may be amended, performance sites may be broad, and obligation amounts differ from actual expenditures.
- Inputs may be duplicated, stale, contradict latest official source, or contain permission-sensitive data.
- Archive-level hashes must not stand in for member-level identity; never silently de-duplicate distinct manifestations.

**Reconciliation:** Pass A C01–C12 cover all threat categories by rule and oracle; distinct secondary checks of security/retention, exact temporal assignment, and contract-amendment lineage remain explicit subchecks of C01/C06/C08. No code execution is authorized by design readiness alone.

Readiness: **DESIGN_READY (scoped documentation); EXECUTION_READY for production = NO_GO**, pending existing router extension-point inspection, GUI/API contract design, test inventory, and source access review.

## Canonical relationship boundaries

```
evidence_artifact --manifestation_of--> source
observation --extracted_from--> evidence_artifact
identifier_assignment --applies_to_during--> aircraft [dated, source-bound]
flight_session --has_candidate_observation--> observation
registered_owner --registration_relation--> aircraft [dated]
operator --operation_relation--> aircraft [dated and independently evidenced]
contract --awarded_to--> organization [official award record]
aircraft --assigned_under--> contract [requires direct airframe evidence]
mission --performed_by--> aircraft [requires explicit mission evidence]
event_correlation --candidate_only--> event [not identity]
```

Permitted states: `FACT, COMPUTED, BINDING, INFERENCE, ASSUMPTION, HYPOTHESIS, UNKNOWN`; conclusion states inherit the governing contract. Preserve `RAW / NORMALIZED / CANONICAL` separately. Store per-relationship evidence IDs, source version and time scope, and reason for state transition. Allow 1:1, 1:N, N:1, N:N, 0:1, UNRESOLVED. Reject any join that multiplies rows without an explicit expected-cardinality receipt.

## N852VB/BATMAN47 frozen screenshot fixture

`tests/fixtures/faei/n852vb_oct2026_screenshots.v1.json` is **not** the FAA registry, not a flight export, and not verified Coast Guard task-order linkage. It records five conversation-upload manifestations, SHA-256 values independently recomputed from the uploaded JPEG bytes, and dated *visible UI observations*. Do not interpret the archive as a complete flight denominator.

Observed UI dates: Oct 11, 15, 16, 17, 18, 22, 24 (2026); exact screenshot instances: Oct 17, 18, 22, 24 plus Oct 11/15/16 history listings. Observation times in the screenshots use UTC-04:00. Registration N852VB, serial VB-200147, Mode S ABB0A3, callsign BATMAN47 are **screenshot assertions** until source-specific official registry versions are frozen and independently verified.

Prohibited promotions:
`FR24_DISPLAY -> FAA_VERIFIED`;
`SCREENSHOT_PATH -> RAW_ADSB_POINTS`;
`SEVEN_DATES -> SEVEN_DISTINCT_FLIGHTS`;
`OWNER -> OPERATOR`;
`SAME_CONTRACTOR_AND_REGION -> AIRFRAME_CONTRACT_BINDING`;
`CONTRACT -> EXACT_MISSION`;
`OFFSHORE_ROUTE -> UAP_MISSION`.

## Domain authority, dependency order, and rollout

1. **Skywatcher**: reuse `src/skywatcher/evidence_router.py`, existing RLSM provenance, FAA adapter, FR24 manifest audit and flight-session models. Add a named investigation profile only after determining real extension points and existing tests. No parallel parser authority.
2. **Spiderweb**: only authoritative geometry and spatial states, with raw track/derived line separation and source uncertainty.
3. **MoneySweep**: award/action/contractor provenance and amendment history; never writes aircraft or mission identity.
4. **OVNIS**: UAP report correlation stored as an explicitly non-binding hypothesis.
5. **Centinelas**: contradiction alerts and review queue; **TheHub**: exact-head federated verification/LOCKSTEP; **Mucaro**: governed orchestration after independent approval.

## Acceptance & recovery

- Preflight: independent two-pass coverage, source rights, repo exact heads, API/schema compatibility, test denominators, negative and adversarial cases.
- Implementation: idempotent source acquisition and append-only manifestations; never overwrite contradictory observations.
- Tests: positive stable-ID binding, null/mismatch/duplicate/reused callsign, timestamp offsets, multi-day listings, missing raw points, source changes, false contract association, spatial uncertainty, and UAP false promotion.
- Postflight: replay the critical claims from immutable evidence by an independently reviewed implementation; rerun changed-head checks.
- Rollback: feature-flag gated capabilities; immutable original and prior receipts; no rewrite of certified baseline.
- Final outcome states: screenshot preservation may PASS independently; **AIRFRAME_CONTRACT_LINKAGE OPEN; MISSION UNKNOWN; FAEI_V1_CERTIFIED WITHHELD** until exact-source and operational gates close.

**Next vector:** inspect actual router/test/GUI contracts → implement internal feature-flagged domain extension → regression harness → GUI parity → independent review → cross-repo consumers → exact-merged-head replay → TheHub LOCKSTEP → scoped certification.
