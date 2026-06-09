# FR24 POI Recurrence Parameter Family Queue

## Status

Queued for FR24 visual-parameter registry v1.

This queue item records the next parameter family requested for the FR24 visual-analysis subsystem:

```text
POI_RECURRENCE_PARAMETER_FAMILY
```

It must be added during the parameter-registry and infrastructure-context phases, not during screenshot privacy/provenance setup.

## Purpose

Identify and list recurrence for:

1. each single unique POI; and
2. each POI layer, meaning a group of locations from one or more ILAP layers.

A POI can be a single unique location. A POI layer can be a grouped set of locations from hydro, utility, transport, industrial, MBIL, palm, terrain, or other ILAP-related layers.

This is a recurrence and aggregation family. It is not a visual-object detector and should not be implemented inside `palm_tree_detection.py`.

## Registry Families

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

## Target Operations

| Operation | Queue action |
|---:|---|
| 13 | Add definitions to `fr24_visual_parameters.json` |
| 14 | Add rows to `fr24_parameter_coverage_matrix.csv` |
| 20 | Map registry parameters to `fr24_poi_recurrence.py` |
| 22 | Map recurrence fields to recurrence sidecars |
| 30 | Connect POI/layer recurrence to infrastructure-context logic |
| 31 | Emit recurrence-ready observation links from observation builder |
| 32 | Aggregate recurrence across screenshot batches |

## Planned Module

```text
fr24_poi_recurrence.py
```

## Planned Exports

```text
poi_recurrence.jsonl
poi_layer_recurrence.jsonl
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

## Implementation Rule

Do not implement this family before these foundations exist:

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
