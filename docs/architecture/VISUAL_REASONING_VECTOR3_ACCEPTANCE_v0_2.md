# Skywatcher Visual Reasoning Vector 3 Acceptance Ledger v0.2.0

**Vector:** 3/3 — Canonical Visual-Reasoning Runtime Implementation  
**Parent:** Vector 2 normalized baseline `097cfcb220e16a0f59ed2ff4b34f07a6f419f2c3`  
**Validated implementation head:** `a030053104c18ad87fe447204b3fe41f2a9ab549`  
**Branch:** `feat/visual-reasoning-runtime-v0-2`  
**PR:** #196  
**State:** `PASS_BOUNDED_RUNTIME_IMPLEMENTATION`  
**Production promotion:** `OPEN — CORPUS_NUMERIC_REPLAY_NOT_CERTIFIED`

## 1. Acceptance boundary

Vector 3 implements the canonical decision/runtime layer established by Vector 1 and normalized against the existing implementation in Vector 2. This acceptance state certifies the bounded implementation and its regression controls. It does **not** certify unvalidated numerical parameter values as production thresholds and it does **not** claim corpus-wide numeric differential replay where normalized observation sidecars are absent.

The distinction is deliberate:

- runtime semantics and fail-closed gates: **PASS**;
- existing labeled calibration controls: **PASS as label/negative-control fixtures**;
- synthetic shadow-mode execution harness: **PASS**;
- production numerical calibration: **OPEN**;
- corpus-wide old-vs-new replay from normalized per-frame metrics: **OPEN / INPUT GAP**.

## 2. Implemented canonical runtime surface

### Core decision engine

`src/skywatcher/satim/visual_reasoning_runtime.py` implements:

- explicit parameter binding with no hidden output-affecting defaults;
- zoom and overzoom adjudication;
- local shadow consistency adjudication;
- seam/stitch discovery and cross-seam continuity;
- digital artifact versus real-world-object candidate adjudication;
- palm morphology reasoning with species non-promotion;
- water presence and hydrographic-form adjudication;
- quarry-versus-natural/ground-disturbance reasoning;
- excavation reasoning with explicit depth gate;
- portal-like visible-feature reasoning with subsurface-identity separation;
- multiscale persistence and below-resolution-not-absence handling;
- multiframe registration/consensus handling;
- scene-graph relations where relation support is not object identity;
- multi-channel scene localization with runner-up preservation, hard contradiction rejection, and exact-location registration gates.

### Infrastructure hierarchy

`src/skywatcher/satim/infrastructure_reasoning.py` implements broad-class-before-subtype reasoning. A supported broad infrastructure class does not force a subtype; tied or insufficient subtype evidence yields `INFRASTRUCTURE_CLASS_ONLY`. A hard falsifier wins over positive support. No infrastructure result establishes legal ownership, facility identity, mission, or intent.

### Pixel-level shadow photometry

`src/skywatcher/satim/shadow_photometry.py` adds actual source-pixel measurements for:

- region mean luminance;
- local illuminated reference luminance;
- relative darkness ratio;
- nearby-shadow median and local deviation;
- local texture and texture retention;
- exact-black/clipping ratio;
- pixel-area provenance.

Photometry alone does not classify shadow identity. The measured values are combined with independent edge/direction/geometry evidence by the canonical shadow adjudicator.

## 3. Runtime audit gate

`scripts/audit_visual_reasoning_runtime.py` statically audits the canonical runtime modules against the frozen parameter and reason-code registries. The gate checks:

1. every uppercase dotted runtime parameter identifier against `parameter_registry_v0_2.yaml`;
2. every emitted `RC_*` reason code against `reason_codes_v0_2.yaml`;
3. prohibited direct references to quarantined legacy mixed-domain surfaces;
4. unregistered floating-point comparison thresholds in canonical runtime modules.

The audit is wired to regression tests and fails closed on any violation.

## 4. Shadow-mode differential harness

`scripts/run_visual_reasoning_shadow_mode.py` provides a non-activating JSON/JSONL runner for normalized observations. It records source identity, optional legacy/baseline state, canonical state, reason codes, change class, and canonical output while permanently setting `production_activated=false`.

The shadow runner explicitly rejects weak-evidence identity promotion. It supports zoom, shadow, seam, artifact, palm, water, quarry, excavation, portal, multiscale, multiframe, and locator observations.

The current repository does not contain a complete corpus of normalized per-frame measurements for every new v0.2 runtime channel. Therefore the harness is executable and tested, but a claim of **full corpus numerical differential replay** would be unsupported. That promotion gate remains open rather than being inferred from labels or screenshots.

## 5. Existing calibration controls

Existing SATIM calibration fixtures are reused as non-promotion and false-positive controls rather than being relabeled as numerical model training data.

The `moca_fr24_2025` set includes palm, water, FR24 3D-render/seam, shadow/tree-crown ambiguity, and compression/smudge cases. The `control_moca_groundtruth` set includes confirmed tile seam, palm crown, water/pool, and other ground-truth controls.

Regression tests enforce the intended interpretation:

- tile seam/render control != real-world boundary;
- palm control != species identity;
- water control != automatic river/stream/canal/reservoir form;
- ambiguous shadow/object control remains ambiguous;
- artifact/render evidence cannot become a scene-locator landmark.

## 6. Sensitivity and boundary tests

Boundary/sensitivity tests explicitly perturb registered values for:

- overzoom resampling damage;
- shadow darkness range;
- seam discrepancy severity;
- artifact real-object promotion;
- palm radiality;
- water candidate threshold;
- quarry natural-scarp negative control;
- locator runner-up margin;
- exact-registration RMSE.

This establishes that decision boundaries are controlled by explicit parameters instead of hidden implementation constants. Test fixture values remain test-only and are **not** promoted to production calibration.

## 7. Key fail-closed regression gates

The runtime regression suite demonstrates:

- missing required parameter -> `UNRESOLVED`;
- overzoom cannot manufacture information confidence;
- dark region alone does not become shadow;
- clipped black is distinct from physical shadow;
- seam does not split a geometrically continuous feature;
- stitch ghost remains an artifact candidate;
- render-scale-dependent feature is excluded from location landmark use;
- coherent multi-scale/multi-frame feature may become only a real-world-object candidate;
- palm species remains unresolved without species evidence;
- dark surface without hydrographic geometry does not become water;
- connected banked channel can support river/stream form;
- bare ground alone does not become quarry;
- visual quarry does not establish legal mine identity;
- excavation depth requires explicit geometry;
- portal-like appearance does not establish subsurface identity;
- below-resolution disappearance is not absence;
- scene relationships do not promote identity;
- one text label cannot certify exact location;
- runner-up candidate is preserved and close scores fail closed;
- hard geometric contradiction rejects a location candidate;
- exact localization is provisional without registration gates;
- exact-certified localization requires control points, RMSE bounds, leave-one-out residual, and explicit error radius;
- artifact-derived landmarks block exact-location promotion;
- shadow mode never activates production output.

## 8. CI certification

Validated head `a030053104c18ad87fe447204b3fe41f2a9ab549`:

- Skywatcher CI run **840**: `SUCCESS`;
- SATIM Runtime Smoke Tests run **372**: `SUCCESS`;
- Federation template drift run **1036**: `SUCCESS`.

Skywatcher CI includes gating Ruff, Python 3.10/3.11/3.12 test legs, imagery tests on 3.11/3.12, frontend tests/build, and lockfile drift checks. Ruff's exact import-order correction was probed in an isolated temporary workflow and applied; the temporary workflow was then removed before this validated head.

## 9. Certification arithmetic

The tri-vector implementation program now has:

- Vector 1: `PASS_BOUNDED_EXHAUSTION` — canonical specification;
- Vector 2: `PASS_BOUNDED_NORMALIZATION` — existing baseline audit and repair;
- Vector 3: `PASS_BOUNDED_RUNTIME_IMPLEMENTATION` — canonical runtime plus bounded verification.

This is **3/3 implementation-vector completion**, not production calibration certification.

## 10. Remaining promotion gates

The following remain explicitly open and must not be silently converted to PASS:

1. production parameter calibration against sufficiently broad labeled/ground-truth distributions;
2. normalized observation sidecars for the full target screenshot/corpus denominator;
3. corpus-wide old-vs-new shadow-mode differential replay on those sidecars;
4. measured false-positive/false-negative and abstention rates by feature family;
5. provider/date/zoom stratified robustness checks;
6. exact-location calibration against independent held-out georeferenced scenes;
7. explicit production activation decision after the preceding gates pass.

## 11. Final Vector 3 verdict

`VECTOR_3_STATE=PASS_BOUNDED_RUNTIME_IMPLEMENTATION`

`TRI_VECTOR_IMPLEMENTATION_STATE=3_OF_3_COMPLETE`

`PRODUCTION_VISUAL_REASONING_STATE=NOT_YET_CERTIFIED`

`BLOCKING_INPUT_GAP=FULL_CORPUS_NORMALIZED_OBSERVATION_SIDECARS`

No unresolved implementation defect discovered in the bounded runtime surface is being hidden by this acceptance state. The open items are calibration/replay/promotion gates, not silently waived implementation failures.
