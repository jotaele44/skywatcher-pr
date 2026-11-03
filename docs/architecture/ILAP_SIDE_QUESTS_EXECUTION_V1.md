# ILAP Visual Scene Reasoning — Side-Quest Execution v1

**Status:** CANDIDATE IMPLEMENTATION / CALIBRATION OPEN  
**Parent:** `ILAP_VISUAL_SCENE_REASONING_CONTRACT_v1_1`  
**Scope:** Execute the nine side quests requested for Puerto Rico scene calibration and analyst review without promoting uncalibrated detector output to identity, purpose, or hidden-infrastructure claims.

## Side-quest denominator

1. Puerto Rico palm/tree corpus.
2. Roof / tarp / pool / glare controls.
3. Vehicle baselines by rural-site type.
4. Path-network controls for agriculture, drainage, trails, and erosion.
5. High / medium / low access-friction reference sites.
6. Multi-analyst annotation comparison.
7. Colorblind-safe GUI palette.
8. Temporal image stack viewer.
9. Candidate explainability pane.

## Corpus rules

All corpus entries require:

- stable `sample_id`;
- raw source reference or immutable local artifact hash;
- source/license field;
- Puerto Rico municipality or `UNKNOWN`;
- imagery date or `UNKNOWN`;
- annotation state;
- analyst provenance;
- positive class and explicit negative/confusion classes;
- quality/occlusion state;
- independent-source lineage where applicable.

A corpus row is not ground truth merely because it is annotated. `GROUND_TRUTH` requires an independently supported binding appropriate to the class. Human-only examples are `ANALYST_LABEL` until adjudicated.

Derived crops, resized copies, screenshots of the same source, and alternate encodings are not independent samples. Split train/validation/test by source manifestation lineage to prevent leakage.

## Palm/tree corpus

Required classes:

- `PALM_LIKE_CROWN`
- `PALM_TREE_CANDIDATE`
- `NON_PALM_TREE_CROWN`
- `BANANA_PLANT_CONFUSER`
- `BROADLEAF_CROWN_CONFUSER`
- `SHADOW_CONFUSER`
- `CANOPY_GAP_CONFUSER`

Species promotion is prohibited from low-resolution imagery. Record crown diameter, radial/frond score, trunk visibility, shadow support, occlusion, and cross-scale persistence where measurable.

## Roof / tarp / pool / glare controls

Required classes:

- `BLUE_ROOF_CANDIDATE`
- `NON_BLUE_ROOF`
- `BLUE_TARP_CONFUSER`
- `POOL_OR_CISTERN_CONFUSER`
- `WATER_SURFACE_CONFUSER`
- `SPECULAR_GLARE_CONFUSER`
- `RENDERING_COLOR_SHIFT_CONFUSER`

Required evidence chain: `BLUE_SURFACE -> ROOF_GEOMETRY -> BLUE_ROOF_CANDIDATE`. Color alone is never sufficient.

## Vehicle baselines

Comparison strata should be defined before anomaly scoring. At minimum:

- rural residence/compound;
- agricultural/farm compound;
- church/religious site;
- school/educational site;
- retail/service site;
- construction/staging site;
- repair/dealership/vehicle-yard site;
- municipal/public works site;
- recreation/event site.

Store raw visible vehicle count, count uncertainty, usable scene fraction, parking-area estimate, imagery date/time if known, and comparison stratum. A raw count never implies unusual activity.

## Path-network controls

Required classes:

- `AGRICULTURAL_ROWS`
- `SERVICE_PATH_NETWORK`
- `TRAIL_NETWORK`
- `DRAINAGE_NETWORK`
- `TERRACING`
- `EROSIONAL_GULLIES`
- `ROAD_NETWORK`
- `UNRESOLVED_PATH_PATTERN`

Useful measurements include path density, branch factor, junction count, loop count, dead-end count, mean segment length, slope alignment, row alignment, and building-connection ratio.

## Access-friction references

Reference sites are calibration controls only. Each site must freeze the exact road-network and terrain snapshots used for scoring. Labels `LOW`, `MEDIUM`, and `HIGH` are provisional until thresholds are empirically calibrated.

Required raw variables:

- straight-line distance;
- network travel distance;
- detour ratio;
- independent access-route count;
- bridge dependency;
- gate/barrier observations;
- road class/surface where available;
- slope and relief;
- settlement density;
- trail/water/coastal access context.

Remoteness is descriptive context, not suspiciousness or purpose.

## Multi-analyst comparison

Store analyst annotations separately. Compare geometry using:

- intersection;
- union;
- A-only;
- B-only;
- symmetric difference;
- IoU;
- centroid displacement;
- class agreement.

Consensus is not created by majority vote when hard evidence contradicts the majority. Tied or materially conflicting labels remain `REVIEW_UNRESOLVED`.

## Colorblind-safe palette

Class color is UI-only. Evidence state is encoded by line/fill style, not hue. Provide both the canonical palette and a colorblind-safe alternative. Never convert analyst markup colors into detector evidence.

## Temporal image stack viewer

The viewer must preserve source lineage and imagery epoch per frame. It must support ordered frames, same-location comparison, frame-level source metadata, feature persistence state, and an explicit `UNKNOWN_DATE` posture. A device screenshot timestamp is not the imagery acquisition time.

## Candidate explainability pane

Every candidate display should expose:

- `WHY_FLAGGED`;
- `OBSERVATIONS`;
- `NEGATIVE_EVIDENCE`;
- `CONTRADICTIONS`;
- `UNKNOWNS`;
- `FALSIFIERS`;
- `NEXT_EVIDENCE`;
- component scores and their calibration states;
- source lineage and independence state.

A high ILAP discovery score remains review prioritization only.

## Certification posture

This side-quest package is not certified until the relevant corpora have frozen denominators, source hashes, train/validation/test leakage controls, positive/negative controls, and executed regression metrics. GUI presence is implementation evidence only.
