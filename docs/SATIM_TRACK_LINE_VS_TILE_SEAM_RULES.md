# SATIM Track-Line vs Imagery-Seam vs UI-Overlay Rules

## Purpose

SATIM must separate visually similar observations from causal identity before any imagery-derived candidate is promoted.

The required distinction is:

1. FR24 track-line overlays;
2. FR24/UI or viewport compositing artifacts;
3. imagery-seam observations;
4. source-mosaic cutlines;
5. renderer/display tile edges;
6. natural shadow boundaries;
7. physical ground features.

`IMAGERY_SEAM` is an observation class. It is **not** a causal identity.

Legacy `TILE_SEAM_*` labels remain supported for historical calibration outputs, but they must be interpreted as visual seam likelihood only. Downstream consumers must use the causal-origin firewall in `satim_tile_seam_classifier.classify_seam_origin` before assigning an origin.

## Evidence axes

Every seam candidate should preserve four independent axes:

| Axis | Allowed examples |
|---|---|
| Observation | `RADIOMETRIC_DISCONTINUITY`, `GEOMETRIC_REGISTRATION_DISCONTINUITY`, `RADIOMETRIC_AND_GEOMETRIC`, `UNRESOLVED` |
| Coordinate behavior | `GROUND_FIXED`, `SCREEN_FIXED`, `TILE_GRID_BOUND`, `MIXED`, `UNRESOLVED` |
| Origin | `SOURCE_MOSAIC_CUTLINE`, `DISPLAY_TILE_EDGE`, `VIEWPORT_COMPOSITING_ARTIFACT`, `NATURAL_SHADOW_BOUNDARY`, `PHYSICAL_GROUND_FEATURE`, `COMPRESSION_OR_RESAMPLING_ARTIFACT`, `UNRESOLVED` |
| State | `PASS`, `FAIL`, `OPEN`, `BLOCKED`, `PROVISIONAL`, `UNRESOLVED` |

## Rule matrix

| Signal | Track line | UI / viewport | Imagery seam observation | Source mosaic | Display tile edge | Ground feature |
|---|---:|---:|---:|---:|---:|---:|
| Matches FR24 route color/opacity | High | Low/Medium | Low | Low | Low | Low |
| Anchored to aircraft route geometry | High | Low | Low | Low | Low | Low |
| Anchored to panel, label, icon, range ring, or viewport | Low | High | Low | Low | Low | Low |
| Radiometric discontinuity across image pixels | Low | Low/Variable | High | High/Variable | High/Variable | Variable |
| Geometric registration discontinuity | Low | Variable | High | Variable | Variable | Variable |
| Screen-fixed while the map is panned | High/Variable | High | Not identity evidence | Low | Low | Low |
| Ground-fixed while the map is panned | Low | Low | Variable | High | High at a fixed zoom | High |
| Bound to provider tile grid | Low | Low | Not identity evidence | Low | Required for display-tile identity | Variable |
| Persists at same ground position across adjacent zooms | Low | Low | Variable | Supportive | Variable; depends on tile pyramid | High/Variable |
| Persists in independent imagery / GIS | Low | Low | Variable | Low/Variable | Low | Supportive; still not identity by itself |
| Authoritative source mosaic metadata binding | Low | Low | Low | Decisive | Low | Low |
| Independent physical-ground binding | Low | Low | Low | Contradiction | Contradiction | Decisive |

### Critical correction: screen lock is not tile-edge proof

A georeferenced renderer tile boundary normally moves with the map when the user pans. Therefore `screen_locked_score` must **not** be used as a promotion gate for `DISPLAY_TILE_EDGE`.

Screen-fixed behavior instead supports `VIEWPORT_COMPOSITING_ARTIFACT`, UI contamination, or another viewport-relative rendering effect.

A `DISPLAY_TILE_EDGE` identity requires provider tile-grid binding or equivalent authoritative renderer evidence.

## Promotion rules

### Probable track line

Classify as `probable_track_line` when:

```text
track_line_overlap >= 0.70
AND route_color_match == true
AND geometry follows recorded FR24 route segment
AND radiometric_delta < 0.50
```

Decision: `suppress` unless a non-overlay source independently supports the same boundary.

### Probable UI / viewport artifact

Classify as `probable_ui_overlay` or `VIEWPORT_COMPOSITING_ARTIFACT` when:

```text
ui_overlay_overlap >= 0.70
OR ui_anchor_match == true
OR candidate intersects label box / panel / icon / range ring mask
OR (screen_fixed_under_pan == true AND ground_fixed_under_pan == false)
```

Decision: `suppress` or retain as artifact evidence; never reinterpret screen lock as a renderer tile-edge identity.

### Imagery seam observation

A still image may support an imagery-seam observation when a radiometric or geometric discontinuity is reproducible within the image.

```text
radiometric_discontinuity == true
OR geometric_registration_discontinuity == true
```

Decision: observation may be `PASS`; causal origin remains `UNRESOLVED` until origin-specific gates are satisfied.

### Source mosaic cutline

`SOURCE_MOSAIC_CUTLINE` may become `PROVISIONAL` when all hold:

```text
observed_discontinuity == true
AND ground_fixed_under_pan == true
AND persists_across_adjacent_zoom_levels == true
AND provider_tile_grid_binding == false
AND independent_ground_feature_binding == false
```

`PASS` requires authoritative source-mosaic metadata binding, unless a future certified rule supplies equivalent authoritative evidence.

### Renderer / display tile edge

`DISPLAY_TILE_EDGE` may reach `PASS` only when:

```text
observed_discontinuity == true
AND provider_tile_grid_binding == true
AND screen_fixed_under_pan != true
AND independent_ground_feature_binding != true
```

Verticality, horizontality, rectilinearity, proximity to a suspected tile boundary, or one-still appearance are discovery evidence only.

### Physical ground feature

`PHYSICAL_GROUND_FEATURE` reaches `PASS` only with an independent physical-ground binding. Examples include authoritative GIS/vector correspondence, independently certified geometry, or other direct binding evidence.

Cross-source persistence alone is supportive but remains `PROVISIONAL` because persistent illumination, land-cover, or processing boundaries can recur.

### Natural shadow boundary

Shadow origin remains `PROVISIONAL` while morphology or illumination is only plausible. Stronger adjudication should use occluder morphology, solar geometry, acquisition-time evidence, and/or temporal imagery.

## Contradiction flags

| Flag | Meaning |
|---|---|
| `track_line_color_conflict` | Candidate looks like a route line but color/opacity does not match known FR24 route styling. |
| `ui_mask_conflict` | Candidate intersects UI mask but also appears in raw imagery. |
| `single_still_origin_claim` | A causal origin was promoted using only one still image. |
| `screen_lock_used_as_tile_identity` | Viewport-relative behavior was incorrectly used to prove a renderer tile edge. |
| `source_mosaic_vs_tile_grid_binding` | Source-mosaic metadata and provider tile-grid evidence conflict. |
| `artifact_vs_physical_ground_binding` | Artifact-origin evidence conflicts with an independent physical-ground binding. |
| `screen_fixed_vs_ground_fixed` | Coordinate-behavior observations conflict and require adjudication. |
| `infrastructure_false_rejection` | Candidate was rejected only because infrastructure alignment exists. |

## Output contract

Every classified candidate should produce:

- one SATIM visual-observation row;
- zero or one artifact-control row;
- the complete origin candidate set with state for each candidate;
- contradiction flags when evidence conflicts;
- `resolved_origin = UNRESOLVED` whenever zero or more than one origin has an uncontradicted `PASS`;
- a review state before any downstream structural promotion.

## Non-negotiable invariants

1. Observation taxonomy is not causal identity.
2. `RADIOMETRIC_DISCONTINUITY != SOURCE_MOSAIC_CUTLINE`.
3. `SOURCE_MOSAIC_CUTLINE != DISPLAY_TILE_EDGE`.
4. `DISPLAY_TILE_EDGE != PHYSICAL_GROUND_FEATURE`.
5. Screen-fixed behavior is not provider tile-grid identity.
6. Missing tests remain `BLOCKED` or `UNRESOLVED`; they never silently become negative evidence.
7. Hard independent bindings override heuristics, but conflicting hard bindings remain unresolved until adjudicated.
8. Deterministic ordering never resolves tied or contradictory origin evidence.
