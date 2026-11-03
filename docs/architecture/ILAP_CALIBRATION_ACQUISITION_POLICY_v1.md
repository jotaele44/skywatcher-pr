# ILAP Calibration Acquisition Policy v1

Status: ACTIVE CANDIDATE POLICY — numeric calibration remains OPEN.

## Purpose
Freeze the acquisition, provenance, licensing, lineage, adjudication, split, and certification gates for the Puerto Rico ILAP visual calibration corpus tracked by issue #282.

## Evidence classes
- `RAW_SOURCE`: acquired source bytes or service response with frozen provenance.
- `DERIVED_SAMPLE`: crop, resize, screenshot, re-encode, contrast adjustment, tile extraction, or other derivative of a source manifestation.
- `ANALYST_LABEL`: human interpretation not yet independently adjudicated.
- `INDEPENDENTLY_ADJUDICATED_LABEL`: class supported by evidence independent of the analyst markup and independent of the derived manifestation.
- `GROUND_TRUTH`: reserved for a bounded control whose identity is independently established to the class definition and whose source/provenance is frozen.

`ANALYST_LABEL != GROUND_TRUTH` and `DERIVED_SAMPLE != INDEPENDENT_SOURCE` are binding invariants.

## Acquisition eligibility
A source may enter the calibration corpus only when all applicable fields are frozen:
1. source family/provider;
2. URL/service/layer/item/product identifier;
3. retrieval UTC;
4. imagery acquisition epoch or `UNKNOWN`;
5. spatial footprint and CRS when available;
6. raw byte SHA256 for acquired files, or response hash for immutable exported service responses;
7. source lineage ID;
8. license/use-constraint state;
9. quality/occlusion state;
10. class role: positive, negative/confuser, contextual, or adjudication-only.

A public URL or blank copyright field is not a license grant. Third-party imagery inside a federal or public viewer remains third-party unless rights are explicitly bound.

## Source-lineage firewall
All derivatives of one source manifestation inherit the same `source_lineage_id` unless authoritative metadata proves a distinct acquisition.

The following never create independent corroboration by themselves:
- crops;
- resized copies;
- screenshots of the same imagery;
- alternate encodings;
- contrast/color adjustments;
- tiles cut from one mosaic;
- repeated analyst annotations of the same pixels.

## Class denominators
The active corpus must preserve complete candidate sets for:

### Palm/tree
`PALM_LIKE_CROWN | PALM_TREE_CANDIDATE | NON_PALM_TREE_CROWN | BANANA_PLANT_CONFUSER | BROADLEAF_CROWN_CONFUSER | SHADOW_CONFUSER | CANOPY_GAP_CONFUSER | UNRESOLVED_VEGETATION`

### Roof/color confusers
`BLUE_ROOF_CANDIDATE | NON_BLUE_ROOF | BLUE_TARP_CONFUSER | POOL_OR_CISTERN_CONFUSER | WATER_SURFACE_CONFUSER | SPECULAR_GLARE_CONFUSER | RENDERING_COLOR_SHIFT_CONFUSER | UNRESOLVED_BLUE_SURFACE`

### Vehicle-baseline strata
`RURAL_RESIDENCE_OR_COMPOUND | AGRICULTURAL_OR_FARM_COMPOUND | RELIGIOUS_SITE | EDUCATIONAL_SITE | RETAIL_OR_SERVICE_SITE | CONSTRUCTION_OR_STAGING_SITE | REPAIR_DEALERSHIP_OR_VEHICLE_YARD | MUNICIPAL_OR_PUBLIC_WORKS_SITE | RECREATION_OR_EVENT_SITE | UNRESOLVED_SITE_TYPE`

### Path-network controls
`AGRICULTURAL_ROWS | SERVICE_PATH_NETWORK | TRAIL_NETWORK | DRAINAGE_NETWORK | TERRACING | EROSIONAL_GULLIES | ROAD_NETWORK | UNRESOLVED_PATH_PATTERN`

### Access-friction references
Raw metrics are primary. `LOW | MEDIUM | HIGH` remain calibration labels only and may not be assigned as certified states until empirical thresholds are frozen.

## Confusion-class rule
Every positive class must have explicit confusers represented in the same spatial-resolution and scene-quality regime where feasible. Detector success on positives without confusion controls is not certification.

## Split rule
Train/validation/test splits are grouped by `source_lineage_id`, not by crop/image filename. No source lineage may cross split boundaries.

## Duplicate/leakage gates
Before any performance metric:
- exact-byte SHA256 duplicates must be collapsed or explicitly retained as repeated manifestations;
- perceptual/geometry near-duplicates must be reviewed for source-lineage leakage;
- same-acquisition tiles/crops cannot cross splits;
- class counts must close after exclusions;
- unresolved license state excludes a sample from train/validation/test use unless the specific use is permitted.

## Adjudication rule
A label can be promoted only through harder evidence. Examples:
- palm: multiscale morphology + independent reference/ground evidence where available;
- blue roof: roof geometry + persistent blue surface + confuser rejection + independent imagery/reference;
- water/pool: hydrographic geometry/context or authoritative feature binding;
- vehicle count: resolvable objects with uncertainty and quality state; anomaly requires comparison population;
- path class: geometry + terrain/context + independent reference where available;
- access friction: frozen road graph + terrain + raw distance/redundancy/barrier metrics.

## Calibration gate
Threshold calibration is forbidden until:
- denominator and confusion classes are frozen;
- source-lineage split is frozen;
- class arithmetic closes;
- unresolved licensing exclusions are applied;
- positive/negative controls are represented;
- leakage/duplication tests pass.

## Composite ILAP score
The composite ILAP discovery score remains disabled until every contributing subsystem has a versioned calibrated model/threshold set and all required component values are available. A high discovery score is review priority only and never establishes purpose, mission, wrongdoing, hidden infrastructure, or underground facilities.
