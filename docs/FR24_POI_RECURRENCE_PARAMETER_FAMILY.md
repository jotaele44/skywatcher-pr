# FR24 POI Recurrence Parameter Family

Status: queued

## Purpose

This queue item defines the future FR24 visual-analysis parameter families needed to identify and list recurrence for individual POIs and grouped POI layers.

A **POI** is a single stable unique location. A **POI Layer** is a grouped set of locations from one or more ILAP layers.

## Registry families

| Family | Purpose |
|---|---|
| `poi_identity` | stable identity for one unique POI |
| `poi_match` | per-observation match between a screenshot/track and a POI |
| `poi_recurrence` | aggregated recurrence by individual POI |
| `poi_layer_identity` | stable identity for a grouped POI layer |
| `poi_layer_match` | per-observation match between a screenshot/track and a POI layer |
| `poi_layer_recurrence` | aggregated recurrence by POI layer |
| `ilap_layer_convergence` | convergence across hydro, utility, road, industrial, MBIL, palm, terrain, and other ILAP families |

## Operation mapping

| Operation | Queue impact |
|---:|---|
| 13 | add registry parameter definitions |
| 14 | add coverage matrix rows |
| 20 | map implementation to `fr24_poi_recurrence.py` |
| 22 | map exports to recurrence sidecars |
| 30 | integrate with infrastructure/POI context |
| 31 | emit recurrence-ready observation links |
| 32 | aggregate recurrence across screenshot batches |

## Export targets

| Export | Contents |
|---|---|
| `poi_recurrence.jsonl` | aggregated recurrence by single POI |
| `poi_layer_recurrence.jsonl` | aggregated recurrence by POI layer/group |

## Deduplication controls

- Deduplicate by `image_sha256` and `screenshot_id` before counting recurrence.
- Track screenshot count separately from flight count.
- Track same-aircraft recurrence separately from multi-aircraft recurrence.
- Require layer-level convergence to be driven by at least two independent ILAP families before applying an amplifier.

## Queue discipline

This item is queued only. It does not interrupt the active `04_SCREENSHOT_PRIVACY_REDACTION_POLICY` vector.
