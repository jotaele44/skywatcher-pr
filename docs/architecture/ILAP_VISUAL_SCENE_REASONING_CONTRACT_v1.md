# ILAP Visual Scene Reasoning Contract v1

**Status:** CANDIDATE / calibration required  
**Parent:** `VISUAL_REASONING_CANONICAL_SPEC_v0_2.md`  
**Scope:** satellite/aerial visual discovery of review-only ILAP candidates. This contract does not establish hidden infrastructure, purpose, mission, wrongdoing, ownership, underground facilities, or causal relationships.

## Canonical meaning

`ILAP` = **Infrastructure-Linked Airspace Point**. An `ILAP_VISUAL_CANDIDATE` is a geographically registered scene/location for which measured visual/spatial characteristics satisfy a declared discovery rule. It is a review-priority object only.

`HIGH_ILAP_CANDIDATE_SCORE != HIDDEN_INFRASTRUCTURE_IDENTITY`.

## Evidence chain

`RAW_BYTES -> PIXEL_OBSERVATION -> OBJECT_CANDIDATE -> SUPPORTED_SCENE_FEATURE -> SCENE_GRAPH -> ILAP_FEATURE_VECTOR -> DISCOVERY_SCORE -> REVIEW`

No stage may skip a required evidentiary layer. Observation and explanation remain separate.

## Required detector families

1. palm/vegetation morphology;
2. surface water/hydrographic form;
3. roof/building/surface material;
4. vehicle/parking detection;
5. road/access/ingress-egress;
6. terrain/slope/relief;
7. earthwork/quarry/clearing;
8. infrastructure objects (tank, tower, utility, fence, parking, pad, portal-like surface candidate);
9. multiscale/multidate persistence;
10. image provenance/artifact controls.

## Palm rules

Promotion ladder: `PALM_LIKE_CROWN -> PALM_TREE_CANDIDATE -> PALM_TREE`. Species promotion from low-resolution imagery is prohibited. Record count, density, cluster geometry, isolated count, and distances to buildings/water/roads when registration quality supports distance measurement.

## Water rules

Color/tone alone is insufficient. Supported forms include pool, cistern, reservoir, pond, river, stream, canal, drainage, wetland/open water, coastal water, and unknown waterbody. Required negative controls include shadow, dark canopy, asphalt, blue roof/tarp, no-data fill, and compression smear.

## Roof/material rules

`COLOR != MATERIAL != OBJECT`. A blue-roof candidate requires both roof geometry and blue-surface evidence. Preserve blue tarp, pool/water, solar glare/specular reflection, and render artifact as competing explanations. Multi-date persistence strengthens a roof/material hypothesis but does not prove material identity.

## Vehicle anomaly rules

A raw vehicle count is descriptive only. `VEHICLE_ACTIVITY_ANOMALY` requires a defined comparison population of comparable nearby sites and imagery conditions. Record observed count, detection uncertainty, usable parking area, vehicle density, vehicle-to-building ratio, comparison-population denominator, median/IQR or other declared robust baseline, percentile/z-score when statistically justified, and imagery epoch/time uncertainty.

Do not infer unusual activity, illegal activity, mission, or purpose from vehicle count alone.

## Accessibility friction / hard-to-reach rules

`HARD_TO_REACH` is a descriptive accessibility-friction construct, not suspiciousness. Candidate variables include road access count, driveway count, road class/width/surface, road termination at site, distance to primary/secondary road, network travel distance, straight-line distance, network detour ratio, slope, local relief, barriers, river crossings, bridge dependency, gate candidate, forest cover, settlement density, trail access, water access, and coastal access.

`network_detour_ratio = network_travel_distance / straight_line_distance` when both distances are valid and > 0.

No weighted accessibility-friction score may be certified until its weights and thresholds are calibrated. Missing network distance is UNKNOWN, not zero.

## Scene graph

Canonical node classes may include: `BUILDING`, `ROAD`, `VEHICLE`, `PARKING_AREA`, `WATER`, `PALM`, `TREE`, `TANK`, `TOWER`, `UTILITY`, `FENCE`, `QUARRY`, `CLEARING`, `EARTHWORK`, `PAD`, `PORTAL_LIKE_SURFACE_CANDIDATE`.

Canonical relation classes may include: `ADJACENT_TO`, `CONNECTED_TO`, `TERMINATES_AT`, `INSIDE`, `NEAR`, `ALIGNED_WITH`, `SEPARATED_BY`, `UPHILL_FROM`, `DOWNHILL_FROM`.

Every relation stores source object IDs, coordinate space, method, uncertainty, and evidence state. Proximity alone does not establish functional linkage.

## ILAP feature vector

The canonical decomposed vector is:

- `visual_structure_score`
- `layout_unusualness_score`
- `accessibility_friction_score`
- `vehicle_activity_anomaly_score`
- `hydrologic_context_score`
- `terrain_context_score`
- `infrastructure_connectivity_score`
- `temporal_change_score`
- `source_corroboration_score`

Each component is independent and preserves raw inputs. A composite discovery score is optional and may be emitted only when a calibrated, versioned weight set is supplied. Otherwise `composite_state = CALIBRATION_REQUIRED`.

## Non-promotion rules

The following alone MUST NOT promote an ILAP candidate:

- blue roof;
- palm trees;
- water body;
- many cars;
- remote location;
- road termination;
- military/government/industrial proximity;
- quarry/earthwork;
- portal-like surface feature.

Multi-feature configuration may increase review priority only under an explicit calibrated rule set.

## Registration gates

Distance/area/network features require adequate geographic registration. Geometry state must distinguish `RAW_PIXEL`, `NORMALIZED_PIXEL`, `GROUND_REGISTERED`, and `PROJECTED_GROUND`. Pixel geometry must never be treated as ground geometry without a validated transform.

## Source independence

Same-provider repeat imagery is persistence evidence, not independent corroboration. Derived copies, resizes, crops, screenshots, and recompressions are never independent sources. Preserve imagery provider/source lineage.

## Falsification-first requirement

Every promoted hypothesis must carry `supporting_evidence`, `contradicting_evidence`, and `falsification_tests_remaining`. Hard falsifiers override heuristic score.

## Null/tie behavior

UNKNOWN remains distinct from zero. Missing critical evidence yields `ABSTAIN_INSUFFICIENT_EVIDENCE`. Material ties yield `REVIEW_UNRESOLVED`; deterministic ordering must never resolve evidentiary ties.

## Certification

Subsystems are certified independently: object detection, segmentation, scene relations, accessibility metrics, anomaly baselines, temporal persistence, source corroboration, and composite ILAP discovery scoring. Script success is not certification.
