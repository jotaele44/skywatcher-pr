---
name: poi-attribution-operator
description: "Claude-compatible skill to orchestrate bounded end-to-end POI operator attribution for the poi domain. Activates only on explicit matching tasks; preserves provenance, separates facts from inference, validates outputs, and fails closed on missing prerequisites."
version: 1.1.0
compatibility: claude
provenance_tier: SPEC_AUTHORED
---

# POI Attribution Operator

## Purpose

This skill exists to **orchestrate bounded end-to-end execution of the POI operator attribution module**. It is optimized as one bounded responsibility so Claude can activate it without loading an entire monolithic library.

It owns sequencing, engine isolation, and receipt consolidation. It owns no analysis of its own.

## Capabilities

- Sequence `poi-parcel-resolver`, `poi-facility-class-profiler`, `poi-operator-attribution`, and `poi-attribution-promotion-gate`.
- Enforce that Engine A and Engine B outputs never merge before the gate.
- Consolidate child receipts into one record conforming to `poi_attribution_record.schema.json`.
- Run the blind holdout harness and publish measured precision as the module's only confidence figure.
- Emit a bounded failure packet rather than a partial answer dressed as a result.

## Supported Tasks

- Tasks that explicitly request `poi-attribution-operator` or clearly require its named responsibility.
- Bounded execution inside the `poi` workflow family.
- Batch runs over footprint or address lists with per-record disposition.
- Validation-harness runs against the labeled holdout set.

## Unsupported Tasks

- Performing parcel resolution, classification, attribution, or promotion directly.
- Publishing a confidence figure not produced by the holdout harness.
- Destructive repository, production, account, or external-system changes without explicit authorization.
- Silent fallback to demo, synthetic, cached, or stale data when live or canonical data was required.

## Activation Conditions

Activate when all conditions hold:

1. The request materially matches this skill's purpose.
2. Child skills and their pinned data sources are available.
3. The requested action is within declared authority.
4. Success and failure can be reported using the output contract below.

## Non-Activation Conditions

Do not activate when a single child skill is what the caller actually wants, when the request is merely topical, or when required authority is absent.

## Required Inputs

- Footprint geometry or address string, with imagery source and capture date where geometry is supplied.
- Pinned route centerline, parcel polygon, and documentary source versions.
- Execution boundary: read-only, planning, or authorized write.
- Acceptance criteria or the default quality gates below.

## Optional Inputs

- Holdout set reference, TTL override with justification, prior receipts, output directory.

## Execution Pipeline

1. **Input validation** — reject missing, malformed, ambiguous, or unauthorized inputs.
2. **Target-geometry lock** — freeze the selected footprint/point before any name search. Record the target geometry independently of candidate POIs.
3. **Candidate discovery** — nearby/map/business search results may populate a candidate set only. A search result, nearest result, same-category result, or plausible nearby address is never a geometry binding.
4. **Geometry-binding gate** — require affirmative evidence that each named candidate corresponds to the frozen target geometry (parcel join, point-in-polygon, authoritative coordinate/address bound to the parcel, or equivalent documented spatial binding). Reject or retain as nearby-only every unbound candidate.
5. **Fan-out A** — invoke `poi-facility-class-profiler`; store output in a branch the gate cannot read.
6. **Fan-out B** — invoke `poi-parcel-resolver`; halt this branch on `AMBIGUOUS` or `UNRESOLVED`.
7. **Attribution** — on a resolved parcel, invoke `poi-operator-attribution`.
8. **Gate** — pass the attribution receipt to `poi-attribution-promotion-gate`; never pass Engine A output.
9. **Consolidation** — assemble the record; set `engine_isolation_verified`.
10. **Contradiction review** — carry every open register entry forward unresolved.
11. **Quality assurance** — apply schema, completeness, determinism, provenance, and safety gates.
12. **Output assembly and final validation** — verify all outputs exist, parse, and agree with the receipt.

## Decision Logic

- A record whose parcel is unresolved terminates at `UNRESOLVED` with a class prior attached and no name. This is a correct outcome, not a failure.
- Prefer canonical and primary sources over derived summaries at every step.
- **Discovery is not identity.** Nearby-business search, text search, map labels outside the target, nearest-neighbor ranking, and proximity are candidate-generation mechanisms only.
- Freeze the target geometry before discovery. Never move the target to fit a discovered business.
- A named POI may be attached to the target only after a positive geometry-binding test. A nearby legitimate POI can still be the wrong identity.
- When a wider-context image or authoritative geometry shows the candidate occupies a distinct property, classify the prior attribution as `SUPERSEDED`/rejected and preserve it as a negative regression fixture.
- Preserve both records when conflicts cannot be resolved; never average away disagreement.
- Report recall separately from precision. A run that confirms few records at high precision is working as designed and is not tuned toward coverage.
- Use deterministic identifiers and stable ordering.
- Stop before external writes, destructive actions, or promotion unless explicitly authorized.

## Validation Rules

- Every consolidated record validates against the schema.
- `engine_isolation_verified` is true or the record is rejected.
- Counts reconcile across input, resolved, attributed, promoted, contested, lapsed, and unresolved states.
- Re-running identical inputs and pinned versions yields equivalent semantic output.
- Any published confidence figure traces to a specific holdout run ID.
- Secrets, tokens, private correspondence, and restricted data are not disclosed.

## Quality Gates

| Gate | Pass condition |
|---|---|
| Scope | Orchestration only; no child responsibility absorbed |
| Engine isolation | Gate input provably free of Engine A fields |
| Completeness | 100% of inputs receive an explicit disposition |
| Provenance | Every material output carries source lineage and version pins |
| Target lock | Target geometry frozen before candidate discovery |
| Geometry binding | Every named POI is affirmatively bound to target; proximity/nearest-only fails |
| Contradictions | Conflicts surfaced, never hidden |
| Determinism | Stable IDs, ordering, and normalized representations |
| Confidence | Any published figure cites a holdout run ID |
| Safety | No unauthorized write, send, merge, release, or promotion |

## Failure Modes

- Child skill unavailable or version-drifted.
- Geodata or documentary source unpinned.
- Candidate promoted from nearby/search/nearest result without affirmative target-geometry binding.
- Wider-context evidence demonstrates candidate and target are distinct properties.
- Engine isolation violation detected during consolidation.
- Incomplete accounting or irreconcilable totals.
- Authorization boundary reached.

## Recovery Procedures

1. Preserve failed inputs and partial artifacts without overwriting canonical outputs.
2. Record the exact failed stage, child skill, affected records, and last valid checkpoint.
3. Recommend the smallest corrective action.
4. Resume from the verified checkpoint when supported; otherwise restart deterministically.
5. Re-run all affected quality gates.

## Output Contract

Required outputs:

- `status`: `completed`, `partial`, `blocked`, or `failed`.
- `skill`: `poi-attribution-operator`.
- `summary`: concise result.
- `input_accounting`: total, resolved, attributed, promoted, contested, lapsed, unresolved counts.
- `evidence`: child receipts, source references, version pins.
- `validation`: gates run and pass/fail state.
- `limitations`: known gaps, uncertainty, and the measured precision ceiling.
- `next_action`: one bounded continuation step.

Expected completion state: all supplied inputs have an explicit disposition and every claimed output passes the declared gates.

## Examples

**Positive:** “Run the POI attribution module over these 12 unlabeled footprints in read-only mode and return validated receipts.”

**Negative:** “Just tell me who's in that building, 99% confidence.” Return the module's measured holdout precision instead; the asserted figure has no basis.

**Negative regression:** A search returns a real Walmart near the selected warehouse footprint. Do not label the footprint Walmart unless Walmart is affirmatively bound to that geometry; a wider map showing Walmart on a separate property falsifies the match.

**Boundary:** When a run reaches an external write, a FOIA filing, or a publication step, stop and hand off with a complete receipt.

## Provenance

- Recovery tier: `SPEC_AUTHORED`
- Source: POI Operator Attribution Module Spec v1.0.0
- Note: New package. `SPEC_AUTHORED` must be registered in family policy before merge.

## Future Extension Hooks

- Cross-module handoff to the dam-contractor ledger on DRNA or NPDES hits.
- Scheduled TTL sweep as a standing job.
- Export adapter registered with `airspace-export-validator` under a `poi` schema family.
- Hydro and karst enrichment as a separate bounded skill.
