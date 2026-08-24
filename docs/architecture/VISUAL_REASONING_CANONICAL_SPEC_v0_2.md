# Skywatcher Visual Reasoning Canonical Logic Specification v0.2.0

**Status:** VECTOR_1_COMPLETE — BINDING STRUCTURE / CALIBRATION-REQUIRED NUMERIC VALUES  
**Baseline:** `jotaele44/skywatcher-pr@c32c68abce2a281fd13d9632687a7cdc10412d0b`  
**Claim:** bounded exhaustion of the declared v0.2.0 visual-reasoning decision surface, not universal exhaustion of all future sensors/classes.

## Authority

This specification extends the frozen Skywatcher Analytical Ontology v2.0. RLSM remains extraction/localization; SATIM owns imagery/terrain interpretation; FPIM owns flight-path interpretation; CORRIM alone combines SATIM and FPIM analytical findings. Existing integrated/legacy runners are implementation surfaces, not ontology authorities.

Where older repository text permits heuristic mission/intent classification, the later frozen ontology controls this Vector: mission, purpose, wrongdoing, target selection and intent are not outputs of this visual-reasoning surface.

PR #184 is open/unmerged. Its useful declarative-lens concepts (declared inputs, parameter IDs, threshold IDs, contradiction tests, degraded behavior, evidence axes) are structurally crosswalked here, but its branch content is not promoted to canonical merely by existence.

## Declared module universe

1. source custody / frame integrity;
2. screen-state parsing;
3. UI/overlay segmentation;
4. OCR/text observations;
5. image quality and zoom/overzoom;
6. illumination field and shadow photometry/geometry;
7. tile seams, stitching, mosaic, orthorectification and rendering artifacts;
8. digital artifact vs real-scene adjudication;
9. land cover, vegetation and palm morphology;
10. surface water and hydrographic form;
11. roads and buildings;
12. infrastructure hierarchy;
13. quarry/extractive landscape;
14. excavation/ground disturbance;
15. portal-like visible surface candidates;
16. multiscale and multiframe persistence;
17. scene relationship graph;
18. scene locator using text + road + hydrography + terrain + buildings + landmarks;
19. image-to-reference registration;
20. external identity binding boundary;
21. domain-specific downstream analysis.

## Mandatory evidence chain

`RAW_BYTES -> PIXEL_OBSERVATION -> DERIVED_IMAGE_FEATURE -> VISUAL_CANDIDATE -> SUPPORTED_SCENE_FEATURE -> RELATIONAL_INFERENCE -> LOCATION_CANDIDATE -> EXTERNAL_BINDING -> CERTIFIED_FINDING`

No stage may silently skip a required evidentiary layer.

## Global invariants

- visible anomaly != digital artifact;
- digital artifact != real-world object;
- real-world object != object/facility/legal identity;
- dark region != shadow;
- dark region != water;
- seam != real-world boundary and seam != manipulation;
- more zoom != more information;
- inpainted/generated/super-resolution pixels != observed evidence;
- palm-like crown != palm species;
- bare ground/exposed rock != quarry;
- portal-like visible feature != underground facility;
- text/name/proximity/nearest != exact location or identity;
- missing != zero/false/negative evidence;
- evidentiary tie != deterministic winner;
- visual quarry classification != legal mine/operator identity.

## Evidence precedence

1. hard falsifier;
2. hard contradiction;
3. authoritative binding;
4. certified geometric match;
5. multiframe convergence;
6. multiscale convergence;
7. single-frame visual support;
8. heuristic discovery.

Hard evidence overrides heuristics. Tied top evidence remains review/unresolved.

## Shadow logic

Shadow classification is local and relational, not an absolute darkness threshold. Evaluate luminance ratio against an illuminated reference, local shadow-field deviation, texture retention, penumbra/edge softness, geometry, direction and neighboring shadows. Class states include `PHYSICALLY_PLAUSIBLE_SHADOW`, `POSSIBLE_SHADOW`, `INCONSISTENT_SHADOW`, `CLIPPED_BLACK`, `RENDERING_DARKENING_CANDIDATE`, `UNRESOLVED`. A dark patch without geometric/photometric support remains unresolved.

## Tile seam and stitching logic

Detect candidate boundaries using abrupt luminance/color/sharpness/texture/noise/compression changes, linear or irregular mosaic borders, geometric offset, ghosting, duplication, truncation, parallax discontinuity and temporal mosaic difference. Quantify discrepancy separately from real-world feature continuity. A seam is an image provenance/rendering observation; it does not by itself prove manipulation, insertion, deletion or a physical boundary.

## Digital artifact vs physical object

Adjudicate geometric coherence, texture, lighting/shadow, perspective, multiscale persistence, multiframe persistence, seam alignment, compression-grid alignment and render-scale dependency. Allowed terminal visual states include `REAL_WORLD_OBJECT_CANDIDATE`, `DIGITAL_ARTIFACT_CANDIDATE`, `RENDERING_ARTIFACT_CANDIDATE`, `TILE_STITCH_ARTIFACT_CANDIDATE`, `MIXED_REAL_OBJECT_PLUS_ARTIFACT`, `AMBIGUOUS`, `UNRESOLVED`. Artifact-classified regions are prohibited scene-locator landmarks.

## Palm and vegetation logic

Promotion ladder: `PALM_LIKE_CROWN -> PALM_TREE_CANDIDATE -> PALM_TREE`. Use radial crown morphology, frond-like directional structure, trunk support when visible, compatible shadow, occlusion state and cross-scale persistence. Species identity is separate and remains unresolved without sufficient evidence.

## Water and hydrography logic

Water requires more than tone/color. Evaluate surface texture/specularity plus channel geometry, banks/shoreline, continuity, meander or closed-shore form and riparian context. Negative controls include tree shadow, dark canopy, asphalt, roof surfaces, no-data fill and compression smear. Supported forms: river, stream, canal, reservoir, lake, pond, lagoon, estuarine/tidal water, wetland open water, flooded area, unknown waterbody.

## Roads, buildings and infrastructure

Infrastructure is hierarchical. Supported top-level domains: transport, water, energy, industrial, communications, extractive, civil works and buildings. Subtype promotion requires subtype-specific geometry/context; unresolved subtype must not be forced.

## Quarry/extractive landscape logic

Bare ground or exposed rock alone is insufficient. Quarry support requires convergent system evidence such as pit/bench/highwall geometry plus haul-road network, stockpiles, processing context, sediment control and/or validated temporal expansion. Mandatory alternatives: natural scarp, landslide, road cut, karst exposure, erosion and construction grading. `QUARRY_SUPPORTED` remains a visual landform/land-use state, not legal mine identity.

## Excavation and ground disturbance logic

Classes include trench, foundation excavation, road cut, utility trench, borrow excavation, earthwork, grading, cut/fill, construction pad, spoil pile, ditch, drainage excavation and demolition disturbance. Qualitative depth requires geometric support (wall/slope/shadow/parallax/spoil relationship) and cannot be inferred from darkness or soil color alone.

## Portal-like visible feature logic

Restricted to visible surface morphology. Require opening geometry plus some combination of slope relation, access relation, structural edge and cross-scale persistence. Mandatory negatives: tree shadow, canopy gap, culvert, bridge shadow, rock overhang and digital artifact. A portal-like feature never establishes an underground facility.

## Multiscale/multiframe logic

More zoom is not automatically more evidence. States include `UNDERZOOMED`, `CONTEXTUAL`, `OPTIMAL_ZOOM`, `OVERZOOMED`, `UNKNOWN`. A feature disappearing because the child/parent frame lacks sufficient resolution becomes `BELOW_RESOLUTION_NOT_ABSENT`, not real-world absence. Wider frames may improve context without creating fine detail.

## Scene locator

The locator is a constraint solver, not a monolithic visual guesser. Preserve all candidates and the runner-up. Independent channels are text, road graph, hydrography, terrain, buildings, landmarks, vegetation context, multiframe evidence and image registration. Hard geometric contradiction overrides text similarity.

Localization levels: `L0_UNKNOWN`, `L1_REGION`, `L2_MUNICIPALITY_CITY`, `L3_NEIGHBORHOOD_BARRIO`, `L4_ROAD_CORRIDOR`, `L5_LOCAL_CLUSTER`, `L6_EXACT_SCENE_ALIGNMENT`, `L7_PIXEL_TO_GROUND`.

Exact location requires unique convergence plus independently validated control points, registration RMSE/error-radius gates and leave-one-out validation. Every emitted coordinate includes an error radius. Text-only, POI-only, nearest-only and proximity-only exact localization are prohibited.

## Nulls, ties, duplicates and contradictions

Missing required input defaults to unresolved/blocking behavior. Missing optional input degrades with a reason code. Candidate sets are preserved. Duplicate records are collapsed only through stable identity or declared exact equivalence. Contradictions remain first-class evidence and may supersede earlier results; they are never silently overwritten.

## Parameter governance

`configs/visual_reasoning/parameter_registry_v0_2.yaml` is the sole Vector-1 parameter denominator. Every output-affecting parameter family in the declared surface is enumerated. Unvalidated numerical values remain `CALIBRATION_REQUIRED`; this prevents invented cutoffs from becoming policy. Any future output-affecting literal, library/model default or hidden configuration value must be registered or explicitly exempted as an algorithmic constant/unit conversion.

## Rule governance

`configs/visual_reasoning/rule_registry_v0_2.yaml` is the sole Vector-1 material-rule denominator. Every material promotion/demotion/rejection/blocking path has a stable rule ID and reason code. The registry inherits the global null, tie and precedence policies in this specification.

## Existing-repo crosswalk decisions

- Frozen Analytical Ontology v2.0 is retained as the higher-order domain authority.
- Existing threshold seed values remain `CANDIDATE`, `PROHIBITED` or project-gated according to that seed; this Vector does not silently validate them.
- Current `src/skywatcher/core/module_boundaries.py` remains implementation reality for Vector 2 to crosswalk.
- Older module-boundary prose permitting speculative mission classification conflicts with the later frozen ontology; the later ontology controls this Vector.
- PR #184 is design input only until separately merged/adjudicated.

## Vector-1 completion

Vector 1 is complete for the declared scope when the parameter denominator, rule denominator, evidence/state/precedence/null policies, module ownership, class ontology, adapter boundary and calibration posture are explicit and frozen on one branch. This is bounded exhaustion of v0.2.0, not a claim that no future sensor, feature, class, rule or parameter can be added.