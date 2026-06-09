# FR24 Allowed Enum Signal Router

## Status

Operation `06_ALLOWED_ENUM_REGISTRY` is implemented as an allowed enum registry plus signal-group router.

## Purpose

The registry prevents parameter drift by centralizing:

- allowed parameter families;
- allowed source methods;
- allowed export targets;
- allowed status and review values;
- pipeline stage order;
- module capability ownership;
- signal-group export routing;
- suppression-before-interpretation rules.

## Pipeline Stage Order

```text
provenance
privacy
tile_suppression
ground_context
infrastructure_context
recurrence
export
```

Tile suppression must run before ground context. This prevents map/tile artifacts, user annotations, FR24 overlays, and basemap seams from being promoted into ground POIs.

## Module Capability Map

| Module | Stage | Purpose |
|---|---|---|
| `fr24_screenshot_model.py` | `provenance` | canonical screenshot identity |
| `fr24_screenshot_provenance.py` | `provenance` | hash, lineage, platform, timestamp/geometry status |
| `fr24_screenshot_privacy.py` | `privacy` | privacy and fixture governance |
| `fr24_tile_analysis.py` | `tile_suppression` | tile/seam/artifact suppression before ground context |
| `fr24_ground_context.py` | `ground_context` | pools, waterbodies, vehicle clusters, clearings, warehouses, and other visual ground signatures |
| `fr24_infrastructure_context.py` | `infrastructure_context` | context overlap and infrastructure relationships |
| `fr24_poi_recurrence.py` | `recurrence` | recurrence aggregation only; no visual detection |
| `fr24_observation_builder.py` | `export` | base observation and sidecar export packaging |

## Signal-Group Routing Rule

Every signal group must declare:

```text
owned_by_module
pipeline_stage
export_targets
recurrence_enabled
suppression_dependencies
interpretation_guardrail
```

## Critical Guardrails

1. `fr24_tile_analysis.py` runs before `fr24_ground_context.py`.
2. `fr24_poi_recurrence.py` must not own visual detection signal groups.
3. Every signal-group export must be an allowed export target.
4. Every signal group must be owned by exactly one declared module.
5. Tile/seam outputs are artifact candidates only, not physical-ground conclusions.
6. Ground-context outputs are visual candidate markers only, not claims of ownership, function, or wrongdoing.

## Machine-Readable Registry

```text
data/reference/fr24_allowed_enum_registry.json
```

## Loader / Validator

```text
fr24_allowed_enums.py
```

## Tests

```text
tests/test_fr24_allowed_enums.py
```
