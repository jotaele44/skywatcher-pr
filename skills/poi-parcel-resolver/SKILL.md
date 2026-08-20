---
name: poi-parcel-resolver
description: "Claude-compatible skill to resolve Puerto Rico linear-referenced addresses and footprints to a catastro parcel key for the poi domain. Activates only on explicit matching tasks; preserves provenance, separates facts from inference, validates outputs, and fails closed on missing prerequisites."
version: 1.0.0
compatibility: claude
provenance_tier: SPEC_AUTHORED
---

# POI Parcel Resolver

## Purpose

This skill exists to **resolve an address string or footprint to a CRIM catastro parcel key**. It is optimized as one bounded responsibility so Claude can activate it without loading an entire monolithic library.

Parcel resolution is the join key for all downstream operator attribution. Most attribution errors in Puerto Rico originate here, not in the naming step, because PR street addressing (`PR-3 Km 15.2, Bo. Hato Puerco`) is linear-referenced and is not resolvable by conventional geocoders.

## Capabilities

- Parse PR route / km / hectómetro / ramal / interior / barrio / sector / municipio address grammar.
- Linear-reference a km marker along a DTOP route centerline from its published origin.
- Intersect the referenced point against catastro parcel polygons with an uncertainty-scaled buffer.
- Emit `RESOLVED`, `AMBIGUOUS`, or `UNRESOLVED` with an explicit fail reason and residual uncertainty.
- Preserve source identity, data-source versions, uncertainty, and transformation lineage.

## Supported Tasks

- Tasks that explicitly request `poi-parcel-resolver` or clearly require its named responsibility.
- Bounded execution inside the `poi` workflow family.
- Batch resolution of address lists into parcel keys with per-row disposition.

## Unsupported Tasks

- Naming any organization. This skill emits parcel keys only.
- Selecting the nearest parcel when several survive the buffer.
- Silent fallback to demo, synthetic, cached, or stale geodata when canonical data was required.
- Promotion of unverified observations into confirmed findings.

## Activation Conditions

Activate when all conditions hold:

1. The request materially matches this skill's purpose.
2. A route centerline source and a parcel polygon source are supplied and version-pinned.
3. The requested action is within declared authority (read-only unless stated otherwise).
4. Success and failure can be reported using the output contract below.

## Non-Activation Conditions

Do not activate when another skill owns the primary responsibility, the request is merely topical, geodata sources are unavailable or unpinned, or the task would require inventing a parcel key.

## Required Inputs

- Address string, or footprint geometry with imagery source and capture date.
- Route centerline source with published km origin and documented reset history.
- Catastro parcel polygon source, version-pinned.
- Execution boundary: read-only, planning, or authorized write.

## Optional Inputs

- Municipio, barrio, or sector qualifiers for disambiguation.
- Side-of-route hint.
- Buffer override, prior receipts, and human adjudications.

## Execution Pipeline

1. **Input validation** — reject missing, malformed, or unpinned geodata sources.
2. **Parse** — apply the address grammar; refuse ambiguous parses rather than guessing.
3. **Hectómetro check** — compute `km_true = km + hm/10`; when `hm` is absent, raise along-route uncertainty to 900 m and record it.
4. **Route validation** — confirm the route exists and its km origin is documented; refuse to linear-reference an undocumented origin.
5. **Linear referencing** — locate the point at `km_true` along the centerline.
6. **Parcel intersection** — buffer by max(default, along-route uncertainty); intersect parcels.
7. **Disambiguation** — apply municipio and side-of-route qualifiers only. Distance is never a tie-breaker.
8. **Output assembly** — emit result, receipt, limitations, and next action.
9. **Final validation** — verify determinism and that every input row has a disposition.

## Decision Logic

- Prefer a coordinate published by a regulator over any linear-referenced estimate.
- When two or more parcels survive, return all candidates as `AMBIGUOUS`; never pick one.
- `Int.` widens the buffer; it never shifts the point off the route.
- An unpopulated municipio list means municipio matches are provisional, not trusted.
- Preserve the raw address string alongside every parsed field.
- Stop before external writes unless the request explicitly authorizes them.

## Validation Rules

- Required fields are present and type-valid.
- Every output record is traceable to one address input and one geodata version pin.
- Counts reconcile across input, resolved, ambiguous, unresolved, and duplicate states.
- Identical inputs and pinned versions yield identical output, including candidate ordering.
- No parcel key is emitted without a stated `resolution_method` and `residual_uncertainty_m`.

## Quality Gates

| Gate | Pass condition |
|---|---|
| Scope | No organization name appears anywhere in output |
| Completeness | 100% of inputs receive an explicit disposition |
| Provenance | Every output carries geodata source and version pin |
| Contradictions | Multi-parcel hits surfaced as candidates, never collapsed |
| Determinism | Stable IDs, sorted candidates, normalized representations |
| Safety | No unauthorized write or promotion |
| Output | Machine-readable result and human-readable receipt agree |

## Failure Modes

- `UNPARSEABLE`, `MISSING_ROUTE`, `MISSING_KM`.
- `UNKNOWN_ROUTE`, `KM_BEYOND_ROUTE_LENGTH`, `KM_ORIGIN_RESET_UNDOCUMENTED`.
- `NO_PARCEL_IN_BUFFER`, `MULTIPLE_PARCELS_NO_TIEBREAK`, `MUNICIPIO_REQUIRED`.
- Geodata source unavailable or unpinned.

## Recovery Procedures

1. Preserve the failed input and partial artifacts without overwriting canonical outputs.
2. Record the failed stage, fail reason, affected rows, and last valid checkpoint.
3. Recommend the smallest corrective action — usually acquiring the hectómetro or a regulator-published coordinate.
4. Resume from the verified checkpoint; otherwise restart deterministically.
5. Re-run all affected quality gates.

## Output Contract

Required outputs:

- `status`: `completed`, `partial`, `blocked`, or `failed`.
- `skill`: `poi-parcel-resolver`.
- `summary`: concise result.
- `input_accounting`: total, resolved, ambiguous, unresolved, duplicate counts.
- `evidence`: geodata sources, version pins, parsed address fields.
- `validation`: gates run and pass/fail state.
- `limitations`: residual uncertainty and unpopulated reference data.
- `next_action`: one bounded continuation step.

Expected completion state: every supplied address has an explicit disposition and every emitted parcel key carries a method and an uncertainty figure.

## Examples

**Positive:** “Resolve these 40 permit addresses to catastro keys using the pinned DTOP and CRIM extracts, read-only.”

**Negative:** “Tell me who operates at this address.” That is `poi-operator-attribution`; this skill only produces the key.

**Boundary:** When resolution returns `AMBIGUOUS`, stop and hand off with the full candidate list rather than proceeding to attribution.

## Provenance

- Recovery tier: `SPEC_AUTHORED`
- Source: POI Operator Attribution Module Spec v1.0.0
- Note: New package. `SPEC_AUTHORED` must be registered in family policy before merge.

## Future Extension Hooks

- Populated municipio and barrio authority lists.
- Documented km-origin reset history per route segment.
- Suite-level addressing inside multi-tenant footprints.
- Alternative resolution via regulator-published coordinates as a first-class method.
