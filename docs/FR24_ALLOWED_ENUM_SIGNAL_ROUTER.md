# FR24 Allowed Enum Signal Router

## Status

Operation `06_ALLOWED_ENUM_REGISTRY` is implemented as an allowed enum registry plus signal-group router.

Tile-analysis expansion `EXPAND_TILE_ANALYSIS_PARAMETER_STACK_v2` is now wired into the registry as an expanded `tile_suppression` pre-ground layer.

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

Tile suppression must run before ground context. This prevents map/tile artifacts, user annotations, FR24 overlays, route lines, UI controls, map labels, and basemap seams from being promoted into ground POIs.

## Module Capability Map

| Module | Stage | Purpose |
|---|---|---|
| `fr24_screenshot_model.py` | `provenance` | canonical screenshot identity |
| `fr24_screenshot_provenance.py` | `provenance` | hash, lineage, platform, timestamp/geometry status |
| `fr24_screenshot_privacy.py` | `privacy` | privacy and fixture governance |
| `fr24_tile_analysis.py` | `tile_suppression` | tile/seam/artifact/ROI suppression before ground context |
| `fr24_ground_context.py` | `ground_context` | pools, waterbodies, vehicle clusters, clearings, warehouses, and other visual ground signatures |
| `fr24_infrastructure_context.py` | `infrastructure_context` | context overlap and infrastructure relationships |
| `fr24_poi_recurrence.py` | `recurrence` | recurrence aggregation only; no visual detection |
| `fr24_observation_builder.py` | `export` | base observation and sidecar export packaging |

## Tile-Analysis v2 Signal Groups

The `fr24_tile_analysis.py` module owns the expanded v2 pre-ground suppression stack:

```text
tile_analysis
seam_anomaly_detection
tile_artifact_suppression
roi_mask_analysis
seam_geometry_v2
tone_texture_v2
geometry_displacement_v2
blur_smear_canopy
mixed_epoch_detection
dem_terrain_mismatch
ui_route_annotation_suppression
shadow_canopy_confusion
seam_context_recurrence
tile_score_breakdown
calibration_expected_outputs
```

All of these groups emit to:

```text
tile_seam_anomalies
```

All of these groups use:

```text
artifact_only
```

as their interpretation guardrail.

## Tile-Analysis v2 Additions

The v2 expansion adds:

- ROI/mask parameters so noisy overlays can be suppressed while clean ground ROIs remain usable;
- hard-boundary and rectangular-patch fields;
- tone, brightness, color-temperature, vegetation-color, texture, and sharpness mismatch fields;
- geometry displacement and cutoff fields for roads, drainage, buildings, and clearings;
- directional smear, zoom blur, low-resolution canopy, and screen-capture compression fields;
- DEM/terrain mismatch fields for slope, hillshade, and orthorectification artifacts;
- mixed-epoch fields for source-date and vegetation-phase conflicts;
- UI, FR24 route-line, Apple Maps, map-label, user-annotation, and symbol-overlay suppression fields;
- shadow/canopy confusion fields;
- seam context and recurrence fields;
- explainable score-breakdown fields;
- calibration expected-output fields for Claude pilot gates.

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
7. ROI-level suppression must override whole-screenshot interpretation.
8. UI overlays, user annotations, FR24 route lines, map labels, and map symbols must be masked before ground-context extraction.
9. Severe blur/smear/canopy/shadow artifacts force review gating or suppression.
10. Mixed-epoch and DEM/terrain mismatch can explain apparent patch anomalies and must be scored before escalation.

## Machine-Readable Registry

```text
data/reference/fr24_allowed_enum_registry.json
```

## Parameter Universe

```text
data/reference/fr24_pre_contract_parameter_universe.json
```

## Loader / Validator

```text
fr24_allowed_enums.py
```

## Tests

```text
tests/test_fr24_allowed_enums.py
```
