# Skywatcher Visual Reasoning Vector 2 Acceptance Ledger v0.2.0

**Vector:** 2/3 — Existing Baseline Audit and Normalization  
**Implementation baseline audited:** `main@c32c68abce2a281fd13d9632687a7cdc10412d0b`  
**Canonical specification parent:** `f4cd10fe0ded17ce03c431cea4bfc05f0bbca82f`  
**Branch:** `refactor/visual-baseline-normalization-v0-1`  
**Scope claim:** bounded exhaustion of the implementation surfaces materially relevant to the v0.2.0 visual-reasoning decision surface; not universal exhaustion of every Skywatcher file.

## What Vector 2 establishes

Vector 2 does not rewrite Skywatcher. It determines which current implementation
surfaces can be retained, which require adapters, which conflict with the frozen
logic, and which capabilities are genuinely missing. It performs only the
normalization necessary to give Vector 3 a clean target.

## Baseline discoveries

1. The repository already has substantial reusable SATIM imagery infrastructure:
   tile-seam classification, mosaic/artifact signals, geometry/reference helpers,
   render comparison, visible earthwork observations, water observations,
   temporal change and contradiction handling.
2. The module-boundary manifest had lagged active implementation: seven newer
   root-level SATIM modules were not explicitly classified.
3. `fr24/rlsm_unlabeled.py` is an optional, non-default RLSM stage but performs
   semantic terrain/object classification (`pad`, `tank`, `quarry`, etc.), which
   conflicts with the frozen RLSM extraction-only boundary.
4. `satim_cut_fill.py` and `satim_road_end.py` combine image-derived geometry with
   route-proximity/ADS-B linkage scores. Those combinations are cross-domain and
   are not canonical SATIM evidence.
5. `satim_water_feature.py` contains reusable surface-water observations but also
   emits a legacy `P_ROUTE_CONFIDENCE_PATCH`, and its class/weight semantics are
   not the full canonical hydrographic-form adjudicator.
6. `satim_visual_route_gap.py` is intrinsically mixed-domain and is therefore a
   legacy compatibility surface rather than canonical SATIM.
7. `satim_artifact_filter.py` contained a silent false-promotion path: low artifact
   evidence automatically recommended `TRUE_SURFACE_FEATURE`. That inverted the
   canonical rule that absence of artifact evidence is not affirmative physical
   object evidence.

## Normalization completed

### Module ownership

- Every root-level `satim_*.py` file is now explicitly classified.
- `satim_visual_route_gap.py` is quarantined in `legacy`.
- `fr24/rlsm_unlabeled.py` is quarantined in `legacy` while remaining available
  to explicit compatibility/orchestrator callers.
- The newer valid imagery modules are explicitly registered under SATIM.

### Artifact fail-closed repair

`ArtifactClass.UNRESOLVED` was added. The automatic recommendation path is now:

- high legacy artifact score -> `IMAGERY_ARTIFACT`;
- middle legacy score -> `REVIEW_REQUIRED`;
- low artifact score -> `UNRESOLVED`.

`TRUE_SURFACE_FEATURE` remains a compatibility enum for an independently
supplied/adjudicated class; it is no longer inferred merely because artifact
support is weak.

This repair changes a semantic false-positive pathway intentionally and is
covered by positive and negative regression gates.

### Parameter debt

`configs/visual_reasoning/legacy_parameter_debt_v0_2.yaml` records discovered
output-affecting legacy values/weight families without promoting them to
validated canonical parameters. The registry explicitly distinguishes
implementation limits from calibration-required decision values.

### Rule/conflict debt

`configs/visual_reasoning/legacy_rule_conflicts_v0_2.yaml` preserves every
material conflict found in this bounded pass, including its severity,
disposition and future migration action. Conflicting historical tests remain
useful evidence of old behavior but are not specification authority.

### Implementation crosswalk

`docs/architecture/VISUAL_REASONING_VECTOR2_CONFORMANCE_LEDGER_v0_2.csv`
maps canonical objects/rules to current paths and classifies them as
`CONFORMS | PARTIAL | CONFLICTS | MISSING | LEGACY_COMPATIBILITY` with a
specific repair/adaptation action.

## Reuse decisions

**KEEP / REUSE:** source custody and RLSM OCR/localization; module-boundary
infrastructure; SATIM geometry/fit/reference primitives; tile-seam/artifact
taxonomy; temporal-change and contradiction-preservation concepts.

**REUSE THROUGH ADAPTER:** artifact signals, water observations, visible
road-end geometry, visible earthwork signals, render differences, patchwork
and ensemble/calibration outputs.

**LEGACY / NONCANONICAL:** semantic RLSM ground-feature pass; P_ROUTE confidence
patches produced from SATIM scene-feature modules; mixed visual-route-gap
module; cross-domain route/ADS-B linkage contributions to SATIM scores.

**MISSING / VECTOR 3:** full local shadow photometry, palm morphology detector,
full water/hydrographic-form adjudicator, quarry-vs-natural-landform
adjudicator, portal-like surface candidate adjudicator, multiscale scene graph
integration and the multi-channel scene locator.

## Regression gates

`tests/test_visual_reasoning_baseline_v0_2.py` enforces:

- explicit classification for every root SATIM implementation file;
- quarantine of mixed-domain compatibility surfaces;
- RLSM semantic ground-feature stage remains non-default;
- low artifact evidence cannot become a true-surface assertion;
- conflict surfaces remain forbidden to canonical consumers;
- legacy numeric values are not mislabeled canonical/validated;
- every recorded rule conflict has a disposition;
- legacy P_ROUTE outputs are not activated by the canonical visual spec.

`tests/test_satim_artifact_filter.py` adds a direct negative regression for the
repaired false-promotion path.

## Arithmetic closure

Root-level `satim_*.py` denominator at the frozen implementation baseline: 16.
After normalization:

- canonical SATIM bucket: 15;
- legacy mixed-domain bucket: 1 (`satim_visual_route_gap.py`);
- unclassified root SATIM files: 0.

Additionally, `fr24/rlsm_unlabeled.py` is explicitly classified as legacy.

## Acceptance state

Structural normalization is complete when repository tests confirm the new
boundary classifications and the fail-closed artifact repair. Vector 3 may then
build the new visual reasoning layer on this normalized baseline without
importing the listed legacy compatibility outputs.

Numeric calibration remains explicitly outside Vector 2; no legacy score or
weight is certified by this pass.
