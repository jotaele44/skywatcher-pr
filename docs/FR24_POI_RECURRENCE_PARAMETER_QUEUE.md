# FR24 POI Recurrence Parameter Family Queue

## Status

Queued for FR24 visual-parameter registry v1.

This queue file records the next parameter families requested for the FR24 visual-analysis subsystem:

```text
POI_RECURRENCE_PARAMETER_FAMILY
ILAP_TLT_SHAG_TAP
SMALL_WATERBODY_LOCATOR
```

These queue items must be added during the parameter-registry, ground-context, and infrastructure-context phases, not during screenshot privacy/provenance setup.

## POI Recurrence Purpose

Identify and list recurrence for:

1. each single unique POI; and
2. each POI layer, meaning a group of locations from one or more ILAP layers.

A POI can be a single unique location. A POI layer can be a grouped set of locations from hydro, utility, transport, industrial, MBIL, palm, terrain, waterbody, pool, or other ILAP-related layers.

This is a recurrence and aggregation family. It is not a visual-object detector and should not be implemented inside `palm_tree_detection.py`.

## POI Registry Families

The queued registry families are:

| Family | Purpose |
|---|---|
| `poi_identity` | stable identity for unique POIs |
| `poi_match` | per-observation match between screenshot/flight and POI |
| `poi_recurrence` | aggregate recurrence for unique POIs |
| `poi_layer_identity` | stable identity for POI groups/layers |
| `poi_layer_match` | per-observation match between screenshot/flight and POI layer |
| `poi_layer_recurrence` | aggregate recurrence for POI layers |
| `ilap_layer_convergence` | stacked ILAP-layer convergence at or near observations |

## ILAP TLT SHAG/TAP Subfamily

`ILAP_TLT_SHAG_TAP` is queued as a controlled subfamily under `POI_RECURRENCE_PARAMETER_FAMILY`.

| Field | Value |
|---|---|
| TLT code | `SHAG` |
| TLT name | `Small House And Gate` |
| candidate role | `TAP` / Target Access Point |
| TLT family | `access_control_microcompound` |
| interpretation | visual candidate only; not proof of function |

### SHAG/TAP Registry Families

| Family | Purpose |
|---|---|
| `ilap_tlt_identity` | stable identity for target-location-type definitions |
| `ilap_tlt_match` | per-observation match between screenshot/flight and TLT signature |
| `ilap_tlt_recurrence` | aggregate recurrence for repeated TLT signatures |
| `access_control_signature` | component flags for gate/house/fence/driveway microclusters |

### SHAG/TAP Component Flags

| Flag | Meaning |
|---|---|
| `small_house_present` | small house/cabin/control-like structure visible |
| `gate_present` | gate or vehicle-control point visible |
| `gatekeeper_house_present` | larger gate-adjacent or control-adjacent structure visible |
| `fence_line_present` | linear boundary/fence line visible |
| `driveway_access_present` | driveway/access corridor visible |

### SHAG/TAP Planned Export

```text
ilap_tlt_recurrence.jsonl
```

## Small Waterbody Locator Subfamily

`SMALL_WATERBODY_LOCATOR` is queued as a controlled POI and ground-context subfamily.

It covers small water and water-infrastructure features such as:

```text
small ponds
farm ponds
stock ponds
irrigation ponds
irrigation reservoirs
small reservoirs
wells
wellheads
cisterns/tanks
golf ponds
retention basins
drainage basins
quarry ponds
small lagoons
swimming pools
residential pools
commercial pools
hotel/resort pools
public pools
school/institutional pools
abandoned or empty pools
unknown pool features
unknown small water features
```

### Small Waterbody Registry Families

| Family | Purpose |
|---|---|
| `small_waterbody_identity` | stable identity for waterbody/well/pool POIs |
| `small_waterbody_match` | per-observation match between screenshot/flight and waterbody feature |
| `small_waterbody_recurrence` | aggregate recurrence for repeated waterbody/well/pool proximity |
| `water_infrastructure_signature` | component flags for pond/reservoir/basin/control structures |
| `well_irrigation_signature` | component flags for wells, wellheads, pump houses, and irrigation support features |
| `pool_signature` | component flags for swimming pools, decks, patios, fenced yards, and abandoned/empty pools |

### Small Waterbody Type Enum

| Enum | Meaning |
|---|---|
| `small_pond` | generic small pond |
| `farm_pond` | agricultural pond |
| `stock_pond` | livestock/pasture pond |
| `irrigation_pond` | pond used or visually consistent with irrigation context |
| `irrigation_reservoir` | small reservoir in irrigation/agricultural context |
| `small_reservoir` | small impoundment/reservoir |
| `well` | well feature |
| `wellhead` | visible wellhead or well-like surface node |
| `cistern_or_tank` | cistern/tank water-storage feature |
| `golf_pond` | pond in golf-course context |
| `retention_basin` | stormwater retention basin |
| `drainage_basin` | drainage/detention basin |
| `quarry_pond` | water-filled quarry/cut feature |
| `small_lagoon` | small lagoon/wetland pool |
| `swimming_pool` | generic swimming pool |
| `residential_pool` | pool in residential context |
| `commercial_pool` | pool in commercial context |
| `hotel_or_resort_pool` | pool in hotel/resort context |
| `public_pool` | public recreation pool |
| `school_or_institutional_pool` | school/institutional pool |
| `abandoned_or_empty_pool` | empty, derelict, or inactive pool-like basin |
| `unknown_pool` | pool-like feature requiring review |
| `unknown_water_feature` | visible water feature requiring review |

### Small Waterbody Component Flags

| Flag | Meaning |
|---|---|
| `pond_present` | small pond visible |
| `well_present` | well feature visible or recorded |
| `wellhead_present` | wellhead-like node visible |
| `irrigation_pond_present` | irrigation pond visible |
| `irrigation_reservoir_present` | irrigation reservoir visible |
| `small_reservoir_present` | small reservoir visible |
| `golf_pond_present` | golf pond visible |
| `retention_basin_present` | retention basin visible |
| `drainage_basin_present` | drainage/detention basin visible |
| `lined_pond_present` | visibly lined pond/basin edge |
| `farm_or_stock_pond_present` | farm or livestock pond context visible |
| `pool_present` | pool-like water feature visible |
| `swimming_pool_present` | swimming pool visible |
| `rectangular_pool_shape_flag` | rectangular or strongly artificial pool geometry visible |
| `pool_deck_or_patio_present` | pool deck/patio context visible |
| `pool_inside_fenced_yard_flag` | pool appears inside fenced yard or enclosure |
| `abandoned_or_empty_pool_flag` | pool-like basin appears dry, empty, or inactive |
| `pump_house_or_wellhead_present` | pump house/wellhead support structure visible |
| `embankment_or_small_dam_present` | small dam/embankment visible |
| `access_road_to_water_present` | road/track leading to water feature |
| `water_control_structure_present` | outlet, inlet, valve, spillway, or control structure visible |

### Small Waterbody Planned Exports

```text
small_waterbody_locator.jsonl
waterbody_recurrence.jsonl
poi_layer_recurrence.jsonl
```

## Target Operations

| Operation | Queue action |
|---:|---|
| 13 | Add definitions to `fr24_visual_parameters.json` |
| 14 | Add rows to `fr24_parameter_coverage_matrix.csv` |
| 20 | Map registry parameters to `fr24_poi_recurrence.py`, `fr24_ground_context.py`, and `fr24_infrastructure_context.py` |
| 22 | Map recurrence fields to recurrence sidecars |
| 28 | Add waterbody/well/pool feature logic to ground-context module |
| 30 | Connect POI/layer/TLT/waterbody/pool recurrence to infrastructure-context logic |
| 31 | Emit recurrence-ready observation links from observation builder |
| 32 | Aggregate recurrence across screenshot batches |

## Planned Modules

```text
fr24_poi_recurrence.py
fr24_ground_context.py
fr24_infrastructure_context.py
```

## Planned Exports

```text
poi_recurrence.jsonl
poi_layer_recurrence.jsonl
ilap_tlt_recurrence.jsonl
small_waterbody_locator.jsonl
waterbody_recurrence.jsonl
```

These exports should remain sidecars. The base observation row should only keep stable links and high-level confidence fields.

## False-Positive Controls

| Risk | Control |
|---|---|
| One screenshot inflates recurrence | deduplicate by `image_sha256` and `screenshot_id` |
| One flight inflates recurrence | track unique flight count separately from screenshot count |
| One aircraft loitering inflates score | separate same-aircraft recurrence from multi-aircraft recurrence |
| Dense POIs confuse nearest-neighbor match | preserve match rank, radius, and confidence |
| Broad layer over-matches | require member-level evidence count |
| ILAP convergence overfit | require multiple independent layer types before applying boost |
| Visual SHAG/TAP overinterpretation | store as candidate visual signature only and require review status |
| Seasonal or dry waterbody misclassification | support dry/seasonal/unknown water-status fields |
| Swimming pool confused with pond | require waterbody type, context, and review status |
| Pond confused with pool | require artificial-geometry, deck/patio, fenced-yard, and context flags |
| Empty pool confused with dry basin | require abandoned/empty pool flag and review status |
| Shadow/canopy confused with water | require visual confidence and contradiction fields |
| Large mapped reservoir confused with small locator | store small_waterbody_type and geometry/radius fields |

## Implementation Rule

Do not implement these families before these foundations exist:

1. screenshot provenance;
2. screenshot privacy/redaction policy;
3. parameter contract layer;
4. allowed enum registry;
5. config/defaults layer;
6. visual QC engine;
7. export sidecar contract.

The queue entry is machine-readable in:

```text
data/reference/fr24_parameter_family_queue.json
```
