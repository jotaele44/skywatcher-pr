---
name: poi-operator-attribution
description: "Claude-compatible skill to join documentary sources to a catastro parcel and emit named role assertions for the poi domain. Activates only on explicit matching tasks; preserves provenance, separates facts from inference, validates outputs, and fails closed on missing prerequisites."
version: 1.0.0
compatibility: claude
provenance_tier: SPEC_AUTHORED
---

# POI Operator Attribution

## Purpose

This skill exists to **join documentary sources to a resolved catastro parcel and emit named role assertions with full lineage**. It is optimized as one bounded responsibility so Claude can activate it without loading an entire monolithic library.

This is Engine B. It is the only skill in the module permitted to emit an organization name, and it proposes state transitions without granting them.

## Capabilities

- Query and join tiered documentary sources against a parcel key.
- Emit four disjoint role fields: `PARCEL_OWNER`, `PERMIT_HOLDER`, `OPERATOR`, `TENANT[]`.
- Run the source independence test and record its result.
- Maintain a contradiction register for conflicting names in the same role with overlapping validity.
- Compute temporal consistency between imagery capture date and evidence validity intervals.
- Preserve source identity, issuing authority, derivation chains, timestamps, and uncertainty.

## Supported Tasks

- Tasks that explicitly request `poi-operator-attribution` or clearly require its named responsibility.
- Bounded execution inside the `poi` workflow family.
- Re-attribution runs triggered by new filings or expired evidence.

## Unsupported Tasks

- Reading, importing, or reasoning from `facility_class` or any Engine A field.
- Granting a promotion state. Proposals only; `poi-attribution-promotion-gate` decides.
- Attribution by amount-matching, footprint-matching, class-matching, or elimination.
- Collapsing the four role fields into a single `operator` string.
- Treating the absence of a basemap label as evidence.

## Activation Conditions

Activate when all conditions hold:

1. The request materially matches this skill's purpose.
2. A catastro parcel key with status `RESOLVED` is supplied.
3. At least one authorized documentary source is reachable.
4. Success and failure can be reported using the output contract below.

## Non-Activation Conditions

Do not activate when the parcel is `AMBIGUOUS` or `UNRESOLVED`, when the caller supplies only imagery, or when another skill owns the primary responsibility.

## Required Inputs

- Catastro parcel key, status `RESOLVED`, with its resolution method and uncertainty.
- Authorized source list with tier assignments.
- Imagery capture date when temporal consistency is to be evaluated.
- Execution boundary.

## Optional Inputs

- Time window, prior receipts, human adjudications, entity gazetteer, prior contradiction register.

## Execution Pipeline

1. **Input validation** — reject unresolved or ambiguous parcels; reject sources without a tier.
2. **Tier-1 sweep** — regulator self-declarations with coordinates: EPA FRS/ECHO, FDA establishment registration, OGPe permisos, DRNA franchises, EQB air permits, OSHA inspections.
3. **Tier-2 sweep** — self-declarations with an address: Departamento de Estado / DDEC, SAM.gov, USAspending, customs importer of record, WARN, Depto del Trabajo, addressed job postings.
4. **Tier-3 sweep** — circumstantial only: livery, signage, geotagged imagery, broker listings.
5. **Role assignment** — assign each assertion to exactly one role field; never infer a role not stated by the source.
6. **Independence test** — different issuing authority AND neither derives from the other; log shared authorities and derivation chains.
7. **Tenancy adjudication** — default `ASSUMED_MULTI`; `SINGLE_DEMONSTRATED` requires affirmative documentary evidence.
8. **Temporal consistency** — compare imagery capture date to evidence validity intervals; emit PASS, FAIL, or INDETERMINATE.
9. **Contradiction review** — open a register entry for every conflicting overlapping assertion.
10. **Output assembly and final validation** — propose a state; verify no Engine A field was read.

## Decision Logic

- A name without a named source is invalid and is rejected, never carried forward.
- FOIA is a last resort, attempted only after public sources are exhausted; record the exhaustion.
- Preserve both records when conflicts cannot be resolved; never average away disagreement.
- Tier-3 corroborates and never establishes. A record supported only by Tier-3 cannot exceed `CANDIDATE`.
- Sources sharing an issuing authority or a derivation chain count as one.
- Mark every inferred field explicitly with its derivation method.
- Stop before external writes, sends, or promotion unless explicitly authorized.

## Validation Rules

- Every role assertion carries `name`, `source_tier`, `source_ref`, `issuing_authority`, `observed_at`, and `method`.
- No output field references `facility_class`; `engine_isolation_verified` must be true.
- Counts reconcile across sources queried, hits, rejected, duplicate, contradictory, and emitted states.
- Identical inputs and source snapshots yield equivalent semantic output.
- No conclusion is promoted beyond its evidence tier.
- Secrets, tokens, private correspondence, and restricted data are not disclosed.

## Quality Gates

| Gate | Pass condition |
|---|---|
| Engine isolation | Zero reads of Engine A output |
| Source presence | Every name has a named, resolvable source |
| Independence | Test executed and result recorded |
| Role separation | Four fields populated separately; no collapse |
| Tenancy | Cardinality explicitly adjudicated |
| Temporal | Consistency computed or explicitly INDETERMINATE |
| Contradictions | Conflicts surfaced, never hidden |
| Safety | No unauthorized write, send, or promotion |

## Failure Modes

- Parcel unresolved or ambiguous.
- Source unreachable, rate-limited, or schema-drifted.
- All candidate sources fail the independence test.
- Imagery capture date unknown, blocking temporal consistency.
- Ownership conflict with another skill.

## Recovery Procedures

1. Preserve the failed input and partial assertions without overwriting canonical outputs.
2. Record the failed stage, source, affected assertions, and last valid checkpoint.
3. Recommend the smallest corrective action.
4. Resume from the verified checkpoint; otherwise restart deterministically.
5. Re-run all affected quality gates.

## Output Contract

Required outputs:

- `status`: `completed`, `partial`, `blocked`, or `failed`.
- `skill`: `poi-operator-attribution`.
- `summary`: concise result.
- `input_accounting`: sources queried, hits, rejected, duplicate, contradictory, emitted.
- `evidence`: role assertions with full lineage and independence-test result.
- `validation`: gates run and pass/fail state, including engine isolation.
- `limitations`: known gaps, unexhausted sources, FOIA candidates.
- `proposed_state`: a state proposal for the gate. Never a granted state.
- `next_action`: one bounded continuation step.

Expected completion state: every source has an explicit disposition and every emitted name carries a named source and a tier.

## Examples

**Positive:** “Attribute roles for catastro 123-456-789-01 across Tier-1 and Tier-2 sources and propose a state, read-only.”

**Negative:** “The building looks like a distribution center, so it's probably the big 3PL in the area.” Refuse; that is class-matching and elimination, both prohibited.

**Boundary:** When the run reaches a promotion decision, stop and hand off the full receipt to `poi-attribution-promotion-gate`.

## Provenance

- Recovery tier: `SPEC_AUTHORED`
- Source: POI Operator Attribution Module Spec v1.0.0
- Note: New package. `SPEC_AUTHORED` must be registered in family policy before merge.

## Future Extension Hooks

- Additional Tier-1 registries as they publish coordinates.
- Suite-level tenant keys for multi-tenant footprints.
- Cross-link to the dam-contractor ledger where a parcel carries a DRNA or NPDES record.
- Automated FOIA-candidate queue with exhaustion evidence attached.
