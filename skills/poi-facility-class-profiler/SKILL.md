---
name: poi-facility-class-profiler
description: "Claude-compatible skill to derive a name-free facility class prior from footprint geometry for the poi domain. Activates only on explicit matching tasks; preserves provenance, separates facts from inference, validates outputs, and fails closed on missing prerequisites."
version: 1.0.0
compatibility: claude
provenance_tier: SPEC_AUTHORED
---

# POI Facility Class Profiler

## Purpose

This skill exists to **derive a facility class prior from footprint geometry, without ever emitting an organization name**. It is optimized as one bounded responsibility so Claude can activate it without loading an entire monolithic library.

This is Engine A of the two-engine attribution design. Its output is advisory. It is structurally incapable of producing a name and is prohibited from participating in any promotion decision.

## Capabilities

- Extract footprint area, orientation, dock-door count and spacing, truck-court depth, trailer and employee stall counts, roof albedo class, rooftop equipment density, refrigeration racks, tank farms, genset pads, transformer-yard area, rail spur, gate count, and distinct entrance clusters.
- Emit one facility class from a closed enumeration, with a calibrated prior.
- Emit a tenancy signature: `SINGLE_LIKELY`, `MULTI_LIKELY`, or `INDETERMINATE`.
- Report measured holdout class accuracy alongside every prior.
- Preserve imagery source, capture date, and tile-seam flags.

## Supported Tasks

- Tasks that explicitly request `poi-facility-class-profiler` or clearly require its named responsibility.
- Bounded execution inside the `poi` workflow family.
- Feature extraction runs that feed class-model training or evaluation.

## Unsupported Tasks

- Naming, guessing, or hinting at any organization, brand, tenant, or contractor.
- Producing or influencing a promotion state.
- Treating the absence of a basemap label as evidence of anything.
- Silent fallback to synthetic or stale imagery when current imagery was required.

## Activation Conditions

Activate when all conditions hold:

1. The request materially matches this skill's purpose.
2. Raster imagery with a stated source and capture date is supplied.
3. A footprint polygon is supplied or can be derived within declared authority.
4. Success and failure can be reported using the output contract below.

## Non-Activation Conditions

Do not activate when the request is actually about identity, when imagery capture date is unknown and the caller needs a temporally valid result, or when another skill owns the primary responsibility.

## Required Inputs

- Raster tile or imagery reference with source and capture date.
- Footprint polygon in WGS84.
- Model version pin.
- Execution boundary.

## Optional Inputs

- Historical imagery for change detection.
- Ground sample distance, sun angle, and off-nadir metadata.
- Prior feature extractions for the same footprint.

## Execution Pipeline

1. **Input validation** — reject imagery without a stated source; flag unknown capture date.
2. **Seam check** — detect orthomosaic seams and tile-age boundaries crossing the footprint; set `tile_mosaic_flag`.
3. **Feature extraction** — measure the declared feature set; leave unmeasurable features null rather than imputing.
4. **Classification** — assign one class from the closed enumeration with a calibrated prior.
5. **Tenancy signature** — derive from distinct entrance clusters, parking segregation, and dock-bank separation.
6. **Contradiction review** — flag feature combinations inconsistent with the assigned class.
7. **Quality assurance** — apply schema, completeness, determinism, and name-absence gates.
8. **Output assembly** — emit result, receipt, limitations, and next action.
9. **Final validation** — confirm zero name-like strings in output.

## Decision Logic

- A null feature is a finding. Never impute a measurement to complete a class signature.
- A high prior is not identity and must never be phrased as though it were.
- `tile_mosaic_flag` true means the class prior is reported but marked temporally unreliable.
- Prefer measured holdout accuracy over asserted confidence in every statement.
- Class disagreement across imagery epochs is preserved as two records, never averaged.
- Stop before any output that names an entity.

## Validation Rules

- Output contains no organization, brand, contractor, or tenant string. Enforced by lexical scan against the entity gazetteer plus a generic corporate-suffix pattern.
- Every emitted feature is traceable to the imagery reference and model version.
- Counts reconcile across input, classified, unclassifiable, and flagged states.
- Identical imagery and model version yield identical output.
- No class is emitted without a stated prior and a stated holdout accuracy.

## Quality Gates

| Gate | Pass condition |
|---|---|
| Name absence | Zero entity-like strings in any output field |
| Scope | No promotion state proposed or implied |
| Completeness | Every footprint receives a class or `UNCLASSIFIED` |
| Provenance | Imagery source, capture date, and model version present |
| Contradictions | Inconsistent feature/class pairs surfaced |
| Determinism | Stable ordering and normalized measurements |
| Output | Machine-readable result and human-readable receipt agree |

## Failure Modes

- Imagery source or capture date missing.
- Footprint geometry invalid or self-intersecting.
- Orthomosaic seam crossing the footprint.
- Model version unpinned.
- Feature extraction below the minimum count needed for classification.

## Recovery Procedures

1. Preserve the failed input and partial features without overwriting canonical outputs.
2. Record the failed stage, affected footprints, and last valid checkpoint.
3. Recommend the smallest corrective action — usually a different imagery epoch clear of the seam.
4. Resume from the verified checkpoint; otherwise restart deterministically.
5. Re-run all affected quality gates.

## Output Contract

Required outputs:

- `status`: `completed`, `partial`, `blocked`, or `failed`.
- `skill`: `poi-facility-class-profiler`.
- `summary`: concise result, name-free.
- `input_accounting`: total, classified, unclassified, flagged counts.
- `evidence`: imagery source, capture date, model version, feature vector.
- `validation`: gates run and pass/fail state, including the name-absence gate.
- `limitations`: null features and measured accuracy ceiling.
- `next_action`: one bounded continuation step.

Expected completion state: every footprint carries a class or `UNCLASSIFIED`, a prior, a measured accuracy figure, and zero entity names.

## Examples

**Positive:** “Classify these 60 footprints from the pinned imagery epoch and return feature vectors, read-only.”

**Negative:** “This looks like a pharma plant, so tell me which pharma company.” Refuse the second half; hand off to `poi-operator-attribution`.

**Boundary:** When the caller asks for a name on the basis of a strong class prior, stop and return the class with an explicit statement that class is not identity.

## Provenance

- Recovery tier: `SPEC_AUTHORED`
- Source: POI Operator Attribution Module Spec v1.0.0
- Note: New package. `SPEC_AUTHORED` must be registered in family policy before merge.

## Future Extension Hooks

- Multi-epoch change detection as a first-class feature.
- Lidar-derived height and volume features where 3DEP coverage and provenance permit.
- Class-specific sub-signatures without weakening the name-absence gate.
- Calibration refresh procedure tied to the validation harness.
