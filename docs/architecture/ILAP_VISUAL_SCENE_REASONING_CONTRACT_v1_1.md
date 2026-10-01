# ILAP Visual Scene Reasoning Contract v1.1

Status: CANDIDATE CANONICAL SUCCESSOR to v1.0; calibration still required for output-affecting thresholds and weights.

## Scope

This extension adds contextual comparison, persistent object identity, scene hierarchy, temporal change, occlusion/completeness, analyst provenance, consensus, explainability, candidate-family taxonomy, path-network morphology, access redundancy, and visual-exposure context to the SATIM -> ILAP review workflow.

ILAP = Infrastructure-Linked Airspace Point. ILAP outputs remain review-priority objects only. They never establish hidden infrastructure, underground facilities, purpose, mission, ownership, wrongdoing, surveillance target, or causal linkage.

## Evidence chain

RAW_SOURCE -> PIXEL_OBSERVATION -> FEATURE_INSTANCE -> PERSISTENT_INSTANCE_CANDIDATE -> SCENE_OBJECT -> SCENE_RELATION -> CONTEXTUAL_COMPARISON -> TEMPORAL_OBSERVATION -> ILAP_COMPONENT -> ILAP_CANDIDATE_FAMILY -> REVIEW_PRIORITY

No stage may silently skip identity, context, or uncertainty gates.

## Persistent instance identity

Every scene feature receives a frame-local immutable feature_id. Cross-frame/provider binding emits a relation state rather than overwriting identity:

- SAME_OBJECT
- POSSIBLE_SAME_OBJECT
- SPLIT
- MERGED
- MISSING_FROM_VIEW
- BELOW_RESOLUTION
- UNRESOLVED

Proximity alone cannot prove SAME_OBJECT. Candidate matching must preserve the complete candidate set and use geometry, appearance, registration uncertainty, temporal plausibility, and independent identifiers where available.

## Parent/child hierarchy

Canonical hierarchy permits SITE -> COMPOUND -> BUILDING -> ROOF and SITE -> MANAGED_PARCEL -> PALM_CLUSTER / ROW_NETWORK / INTERNAL_PATH_NETWORK, plus PARKING_AREA -> VEHICLE and analogous structures. Parent containment is a measured spatial relation, not ownership or function.

## Context rings

Every registered candidate should support multi-radius context windows. Default radii are schema examples, not validated decision thresholds: 0-50 m, 50-250 m, 250-1000 m, 1-5 km. If ground registration is insufficient, context rings remain UNKNOWN rather than being approximated from screen pixels.

## Local comparison / anomaly logic

Unusualness requires a declared comparison population. Store comparison_set_id, selection rule, N, geography, terrain/land-use strata, imagery epoch/provider constraints, and exclusion rules. Vehicle, building, roof-color, palm-density, road-access, settlement-density, and layout claims may report descriptive percentiles only after the comparison denominator is frozen.

No comparison set -> ABSTAIN_INSUFFICIENT_EVIDENCE or CALIBRATION_REQUIRED. Visual interest is not unusualness.

## Counterfactual nearest controls

For every promoted review candidate, preserve nearest comparable non-candidate controls and the feature-difference vector. Nearest-only is discovery, not equivalence. Tied controls remain tied.

## Negative evidence / visibility

Negative observations must distinguish:

- OBSERVED_ABSENT
- NOT_VISIBLE_OCCLUDED
- NOT_VISIBLE_OUT_OF_FRAME
- BELOW_RESOLUTION
- NOT_MEASURED
- UNKNOWN

NOT_VISIBLE != ABSENT.

Required occlusion channels when measurable: canopy, shadow, cloud, building, UI/labels, no-data, and unknown occlusion. Emit visible_ground_fraction and site_visibility_state: COMPLETE | MOSTLY_VISIBLE | PARTIALLY_VISIBLE | HEAVILY_OCCLUDED | UNKNOWN_EXTENT.

## Boundary uncertainty

Analyst-drawn and machine-derived boundaries must carry method, coordinate_space, uncertainty, and revision. Hand-drawn markup defaults to ANALYST_APPROXIMATE_BOUNDARY. Support core_area, uncertainty_buffer, and possible_extent. Markup geometry never becomes exact GIS geometry by determinism alone.

## Temporal evolution

Temporal observations preserve source/provider/epoch lineage. Supported change classes include NO_CHANGE, CLEARING, GRADING, FOUNDATION, STRUCTURE_ADDITION, ROAD_EXTENSION, VEGETATION_REMOVAL, REVEGETATION, DEMOLITION, WATER_CHANGE, VEHICLE_CHANGE, UNKNOWN_CHANGE.

Derived copies and same-provider render repeats are not independent corroboration. Multi-date persistence != physical identity.

## Functional morphology

Scene morphology may be described as RESIDENTIAL_LIKE, AGRICULTURAL_LIKE, INDUSTRIAL_LIKE, UTILITY_LIKE, INSTITUTIONAL_LIKE, STORAGE_LIKE, MIXED_USE_LIKE, or UNRESOLVED. These are visual morphology states only; they do not establish actual function, ownership, or legal use.

## Path-network morphology

Measure path_count, path_density, branching_factor, junction_count, mean_segment_length, loop_count, dead_end_count, slope_alignment, row_alignment, and building_connection_ratio when resolution allows. Supported descriptive classes: AGRICULTURAL_ROWS, SERVICE_PATH_NETWORK, TRAIL_NETWORK, DRAINAGE_NETWORK, TERRACING, EROSIONAL_GULLIES, UNRESOLVED.

## Compound centrality

Describe structure organization as CENTRAL, EDGE_LOCATED, DISTRIBUTED, LINEAR, CLUSTERED, DISPERSED, or UNRESOLVED. Centrality is spatial layout, not importance or purpose.

## Access redundancy

Measure independent vehicle access routes, single-point-of-failure candidates, bridge dependency, gate dependency, road-end dependency, and seasonal-access candidates. Hard-to-reach/accessibility scores remain calibration-gated and must not use forest cover alone as evidence of inaccessibility.

## Visual exposure

Use neutral VISUAL_EXPOSURE context: canopy cover, viewshed exposure, road visibility, neighbor visibility, ridge screening, terrain enclosure. Do not infer concealment intent.

## Analyst provenance and color markup

Every annotation records annotation_id, analyst_id or system_id, timestamp, source frame, revision, geometry, coordinate space, class, subclass, UI color, evidence state, confidence semantics, notes, and supersession links. Original unmarked pixels remain immutable; marked images are derived artifacts.

Color is UI encoding only. Class color != evidence state != identity. Human markup != ground truth.

## Multi-analyst consensus

For comparable annotations compute INTERSECTION, A_ONLY, B_ONLY, UNION, SYMMETRIC_DIFFERENCE, IoU, Hausdorff distance where geometry permits. Preserve disagreements; do not average them into a fabricated consensus. Tied top interpretations remain REVIEW_UNRESOLVED.

## Human vs machine adjudication

Record HUMAN_YES/MACHINE_YES, HUMAN_YES/MACHINE_NO, HUMAN_NO/MACHINE_YES, and HUMAN_NO/MACHINE_NO against a frozen adjudicated control set. Derived precision/recall metrics must identify corpus/version and class denominator.

## Candidate explainability packet

Every ILAP review candidate must export:

- WHY_FLAGGED
- WHAT_WAS_OBSERVED
- WHAT_WAS_NOT_OBSERVED
- WHAT_REMAINS_UNKNOWN
- SUPPORTING_EVIDENCE
- CONTRADICTING_EVIDENCE
- WHAT_WOULD_FALSIFY_IT
- WHAT_DATA_IS_NEEDED_NEXT
- COMPARISON_SET
- SOURCE_LINEAGE

## ILAP candidate families

A site may belong to zero, one, or many review families:

- ILAP_VISUAL_LAYOUT_CANDIDATE
- ILAP_ACCESSIBILITY_CANDIDATE
- ILAP_HYDRO_CONTEXT_CANDIDATE
- ILAP_INFRASTRUCTURE_CANDIDATE
- ILAP_TEMPORAL_CHANGE_CANDIDATE
- ILAP_ACTIVITY_ANOMALY_CANDIDATE
- ILAP_AIRSPACE_CORRELATION_CANDIDATE

Family membership is decomposable discovery evidence, not a hidden-purpose assertion.

## Mandatory invariants

- Visual interest != unusualness.
- Unusualness != purpose.
- Not visible != absent.
- Hand-drawn boundary != exact geometry.
- Multi-date persistence != identity.
- Similarity != equivalence.
- Nearest control != same class.
- Local baseline required for anomaly claims.
- Human markup and machine detection remain separate evidence streams.
- Same-provider repeat != independent corroboration.
- Derived image != independent source.
- Forested setting != hard to reach.
- Access friction != concealment.
- Candidate family != facility identity.
- Composite ILAP score, if ever enabled, is review prioritization only.

## Certification

Subsystems certify independently: source custody, object detection, persistent identity, hierarchy, occlusion, context comparison, temporal change, path morphology, accessibility, analyst consensus, scene graph, candidate-family assignment, and explainability. Implementation presence is not certification. Composite scoring remains blocked until all required component denominators and versioned calibration weights close with positive and negative controls.