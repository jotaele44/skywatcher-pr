---
name: poi-attribution-promotion-gate
description: "Claude-compatible skill to adjudicate POI attribution state transitions as the sole promotion authority for the poi domain. Activates only on explicit matching tasks; preserves provenance, separates facts from inference, validates outputs, and fails closed on missing prerequisites."
version: 1.1.0
compatibility: claude
provenance_tier: SPEC_AUTHORED
---

# POI Attribution Promotion Gate

## Purpose

This skill exists to **adjudicate state transitions for POI attribution records**. It is the sole authority permitted to change a record's state, and it is optimized as one bounded responsibility so Claude can activate it without loading an entire monolithic library.

States: `UNRESOLVED` · `CANDIDATE` · `PROBABLE` · `CONFIRMED` · `CONTESTED` · `LAPSED`.

## Capabilities

- Evaluate a proposed transition against the declared rule table.
- Verify engine isolation: reject any proposal whose evidence set touches Engine A output.
- Verify source independence, temporal consistency, role separation, and tenancy adjudication.
- Demote and lapse records without requiring new evidence.
- Emit an immutable state-history entry with the rule applied and the evidence relied upon.

## Supported Tasks

- Tasks that explicitly request `poi-attribution-promotion-gate` or clearly require its named responsibility.
- Bounded execution inside the `poi` workflow family.
- Scheduled TTL sweeps that lapse stale `CONFIRMED` records.

## Unsupported Tasks

- Gathering evidence. The gate evaluates; it does not search.
- Granting a transition on any condition not in the rule table.
- Resolving a `CONTESTED` record by inference, averaging, or preference for the higher tier.
- Silent fallback to a prior state when evaluation fails.

## Activation Conditions

Activate when all conditions hold:

1. A complete attribution receipt with a `proposed_state` is supplied.
2. The record validates against `poi_attribution_record.schema.json`.
3. The requested action is within declared authority.
4. Success and failure can be reported using the output contract below.

## Non-Activation Conditions

Do not activate on partial receipts, on records whose parcel status is not `RESOLVED`, or when the caller asks the gate to also collect evidence.

## Required Inputs

- Attribution receipt from `poi-operator-attribution`, including `proposed_state`.
- Current record state and state history.
- Independence-test result, temporal-consistency result, contradiction register.
- Execution boundary: evaluation-only or authorized state write.

## Optional Inputs

- TTL override with justification, human adjudications, prior gate run IDs.

## Execution Pipeline

1. **Input validation** — reject incomplete receipts and schema failures.
2. **Engine isolation check** — reject if `engine_isolation_verified` is not true, or if any evidence reference resolves into Engine A output.
3. **Label-absence check** — reject if any evidence item asserts the absence of a basemap label as support.
4. **Target-binding check** — reject promotion when a named assertion is supported only by proximity, nearest-neighbor rank, search-result rank, same category, or an unbound nearby map label. Require affirmative binding to the resolved target parcel/geometry.
5. **Rule lookup** — select the transition rule for the current-to-proposed pair; reject unlisted pairs.
6. **Condition evaluation** — evaluate every condition of that rule; a single failure blocks the promotion.
7. **Contradiction check** — any `OPEN` register entry blocks `CONFIRMED` and forces `CONTESTED` where applicable.
8. **Demotion sweep** — apply lapse and demotion rules regardless of the proposal.
9. **Write or report** — write the state only under authorized write mode; otherwise report the verdict.
10. **Final validation** — confirm the state-history entry, rule identifier, and evidence references are all present.

## Decision Logic

Transition rules:

| From | To | Condition |
|---|---|---|
| UNRESOLVED | CANDIDATE | parcel `RESOLVED` and at least one Tier-2 or Tier-3 assertion joins to it |
| CANDIDATE | PROBABLE | at least one Tier-1, or two independent Tier-2, same catastro, temporal window satisfied |
| PROBABLE | CONFIRMED | two independent sources including at least one Tier-1, temporal consistency PASS, contradiction register empty, role fields disambiguated, tenancy cardinality adjudicated, `tile_mosaic_flag` false |
| any | CONTESTED | conflicting names in one role with overlapping validity intervals |
| CONFIRMED | LAPSED | newest corroborating source older than TTL (default 540 days) or governing permit expired |
| any | UNRESOLVED | parcel key retracted or invalidated |

Invariants:

- Engine A output may not appear in any condition. Enforced, not assumed.
- Absence of a map label is not evidence and may not appear in any condition.
- Proximity is discovery, not identity. `NEAREST_ONLY`, `PROXIMITY_ONLY`, search-result rank, and same-category evidence cannot satisfy a named-POI binding condition.
- Evidence that the candidate occupies a distinct property is a falsifier: deny promotion and route the conflicting attribution for supersession/contradiction handling.
- Promotion requires evidence; demotion never does. The asymmetry is deliberate.
- `CONTESTED` never auto-resolves. Both assertions persist until adjudicating evidence arrives or the record is split.
- Skipping a state is prohibited. `CANDIDATE` cannot jump to `CONFIRMED`.
- When evaluation is indeterminate, hold the current state and report `blocked`.

## Validation Rules

- Every granted transition names the rule applied and the evidence relied upon.
- State history is append-only; prior entries are never rewritten.
- Counts reconcile across proposed, granted, denied, demoted, and lapsed states.
- Identical receipts and rule table version yield identical verdicts.
- No transition is granted on a condition absent from the table.

## Quality Gates

| Gate | Pass condition |
|---|---|
| Engine isolation | No Engine A field reachable from the evidence set |
| Target binding | Named assertions have affirmative target parcel/geometry binding; proximity-only fails |
| Rule coverage | Proposed pair exists in the table |
| Condition completeness | Every condition evaluated, none skipped |
| Contradictions | Open entries block CONFIRMED |
| Append-only | State history extended, never modified |
| Determinism | Same receipt yields same verdict |
| Safety | No state write outside authorized write mode |

## Failure Modes

- Incomplete receipt or schema failure.
- Unlisted transition pair.
- Engine isolation not verified.
- Temporal consistency INDETERMINATE where the rule requires PASS.
- Rule table version unpinned.

## Recovery Procedures

1. Preserve the receipt and the denied verdict; do not overwrite the current state.
2. Record the failed condition by name, not merely the outcome.
3. Recommend the smallest corrective action — usually one specific additional independent source.
4. Resume evaluation when the corrective evidence arrives.
5. Re-run all affected quality gates.

## Output Contract

Required outputs:

- `status`: `completed`, `partial`, `blocked`, or `failed`.
- `skill`: `poi-attribution-promotion-gate`.
- `summary`: verdict in one line.
- `input_accounting`: proposed, granted, denied, demoted, lapsed counts.
- `evidence`: rule identifier, conditions evaluated, per-condition result.
- `validation`: gates run and pass/fail state.
- `limitations`: what specifically is missing for the next promotion.
- `next_action`: one bounded continuation step.

Expected completion state: every proposal receives a verdict naming the rule and every failed condition.

## Examples

**Positive:** “Evaluate this PROBABLE-to-CONFIRMED proposal against the pinned rule table, evaluation-only.”

**Negative:** “The class prior is 0.94, promote it.” Denied at the engine isolation gate.

**Boundary:** When a proposal would require new evidence, stop and hand back to `poi-operator-attribution` naming the exact source class needed.

## Provenance

- Recovery tier: `SPEC_AUTHORED`
- Source: POI Operator Attribution Module Spec v1.0.0
- Note: New package. `SPEC_AUTHORED` must be registered in family policy before merge.

## Future Extension Hooks

- TTL derived from observed permit-renewal intervals rather than the 540-day placeholder.
- Record-splitting procedure for durable `CONTESTED` cases.
- Rule-table versioning with a migration path for already-granted states.
