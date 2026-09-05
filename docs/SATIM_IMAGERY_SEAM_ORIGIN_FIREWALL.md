# SATIM Imagery-Seam Origin Firewall

## Status

- Scope: SATIM screenshot imagery-seam classification.
- Purpose: prevent a visible seam from being silently promoted to a source mosaic cutline, renderer/display tile edge, viewport artifact, natural shadow, or physical ground feature.
- Baseline regression key: `4645a79a391dcd3508e4024cd8ec234caf6871e085df8badc8524f42219fef3c`.
- Raw baseline screenshot: intentionally not committed.
- Derived fixture: `data/calibration/imagery_seam_regression_4645a79a_v0_1.json`.

## Core rule

Observation taxonomy is not causal identity.

```text
RADIOMETRIC_DISCONTINUITY
    != SOURCE_MOSAIC_CUTLINE

SOURCE_MOSAIC_CUTLINE
    != DISPLAY_TILE_EDGE

DISPLAY_TILE_EDGE
    != PHYSICAL_GROUND_FEATURE
```

A deterministic classifier may rank candidates, but ranking is not identity evidence.

## Four-axis representation

Every seam candidate must preserve:

1. **Observation** — what is visibly or quantitatively detected.
2. **Coordinate behavior** — how the candidate behaves under pan/zoom and grid tests.
3. **Origin candidate set** — every causal origin still supported or unresolved.
4. **Certification state** — `PASS`, `FAIL`, `OPEN`, `BLOCKED`, `PROVISIONAL`, or `UNRESOLVED`.

No output may collapse these axes into one overloaded label.

## Baseline regression specimen

The frozen derived specimen establishes:

- `RADIOMETRIC_DISCONTINUITY = PASS`;
- median right-minus-left luminance = `-8.5708`;
- 25-row block-bootstrap 95% interval = `[-10.5682, -7.4252]`;
- right side darker on `92.60%` of analyzed trace rows;
- sign-coherence rank = `1/61` among parallel shifted controls;
- CIEDE2000 median-side difference = `2.684`;
- apparent 10–90 transition width = `25.65 px`.

These values certify a persistent radiometric boundary in the supplied still. They do **not** certify causal origin.

Current origin state for the baseline:

| Origin | State |
|---|---|
| `SOURCE_MOSAIC_CUTLINE` | `BLOCKED` |
| `DISPLAY_TILE_EDGE` | `BLOCKED` |
| `VIEWPORT_COMPOSITING_ARTIFACT` | `BLOCKED` |
| `NATURAL_SHADOW_BOUNDARY` | `UNRESOLVED` |
| `PHYSICAL_GROUND_FEATURE` | `UNRESOLVED` |
| `COMPRESSION_OR_RESAMPLING_ARTIFACT` | `OPEN` |

`resolved_origin = UNRESOLVED`.

## Pan/zoom coordinate-behavior protocol

For a candidate already detected in one still, collect controlled observations without changing the target ground area more than necessary.

### P0 — baseline

Freeze source bytes and SHA-256 before any derived work.

Record:

- source hash;
- view/app family;
- zoom state if observable;
- orientation/pitch if observable;
- candidate trace geometry in screenshot coordinates;
- no causal label beyond observation class.

### P1 — slight pan, same zoom

Move the map enough that the target ground area changes screen position while retaining the candidate area.

Classify:

- `GROUND_FIXED` if the candidate follows the same ground geometry;
- `SCREEN_FIXED` if it remains at the same viewport position while ground moves;
- `UNRESOLVED` if registration cannot be established.

Important: a georeferenced renderer tile boundary can be ground-fixed at a given zoom. Therefore ground-fixed behavior alone does not distinguish a source mosaic cutline from a display tile edge.

### Z-1 and Z+1 — adjacent zooms

Capture one level lower and one level higher while preserving the same ground target.

Measure:

- same-ground candidate persistence;
- geometric displacement relative to stable ground anchors;
- whether the boundary aligns with a known provider tile grid at each zoom;
- whether its morphology changes with the imagery pyramid.

Do not infer display-tile identity from disappearance or movement alone; provider tile-grid binding is required for `DISPLAY_TILE_EDGE = PASS`.

## Origin-specific gates

### `SOURCE_MOSAIC_CUTLINE`

May become `PROVISIONAL` when:

```text
observed_discontinuity == true
AND ground_fixed_under_pan == true
AND persists_across_adjacent_zoom_levels == true
AND provider_tile_grid_binding == false
AND independent_ground_feature_binding == false
```

`PASS` requires authoritative source mosaic/acquisition metadata or an equivalent future certified binding.

### `DISPLAY_TILE_EDGE`

May become `PASS` only when:

```text
observed_discontinuity == true
AND provider_tile_grid_binding == true
AND screen_fixed_under_pan != true
AND independent_ground_feature_binding != true
```

Screen lock is not tile-edge proof. Screen-fixed behavior instead supports viewport-relative rendering or UI contamination.

### `VIEWPORT_COMPOSITING_ARTIFACT`

May become `PASS` when:

```text
screen_fixed_under_pan == true
AND ground_fixed_under_pan == false
```

### `PHYSICAL_GROUND_FEATURE`

May become `PASS` only through independent physical-ground binding.

Cross-source persistence, proximity, visual similarity, and category agreement are discovery/support evidence only.

### `NATURAL_SHADOW_BOUNDARY`

Requires illumination/occluder evidence. Useful tests include:

- shadow morphology;
- plausible occluder geometry;
- solar-geometry consistency when acquisition time is known;
- temporal variation across independent imagery.

Until then it remains `PROVISIONAL` or `UNRESOLVED`.

## Independent source-vs-physical causation protocol

When the exact ground target is known, compare against an independent imagery/GIS source.

Classify outcomes:

- boundary absent in independent source -> source-specific processing/artifact hypothesis strengthened;
- boundary present but morphologically different -> retain source-processing and physical/illumination candidates;
- boundary present with independent vector/ground binding -> physical-ground candidate strengthened or passed depending on binding quality;
- no comparable coverage -> `BLOCKED`, not negative evidence.

Source taxonomy must never be treated as canonical identity.

## Regression gates

Positive tests must establish that:

- one still can pass `RADIOMETRIC_DISCONTINUITY` while `resolved_origin` remains `UNRESOLVED`;
- provider tile-grid binding can pass `DISPLAY_TILE_EDGE`;
- authoritative source-mosaic metadata can pass `SOURCE_MOSAIC_CUTLINE`;
- independent ground binding can pass `PHYSICAL_GROUND_FEATURE`.

Negative tests must establish that:

- screen lock does not pass `DISPLAY_TILE_EDGE`;
- ground-fixed + zoom persistence without metadata does not pass `SOURCE_MOSAIC_CUTLINE`;
- the legacy `TILE_SEAM_PROBABLE` visual label does not resolve causal origin;
- missing pan/zoom/grid evidence remains blocked rather than defaulting to false;
- conflicting hard bindings are preserved as contradictions and fail closed.

## Repository implementation

The firewall is implemented in:

- `satim_tile_seam_classifier.py` — candidate-set-preserving origin classifier;
- `fr24/calibration/l5_tile_seam_shadow_calibration.py` — strict origin-aware L5 gates;
- `tests/test_satim_imagery_seam_origin_firewall.py` — central positive/negative regression tests;
- `tests/test_l5_imagery_seam_origin_gates.py` — L5 origin gate tests;
- `docs/SATIM_TRACK_LINE_VS_TILE_SEAM_RULES.md` — corrected screen-lock and promotion semantics;
- `data/calibration/imagery_seam_regression_4645a79a_v0_1.json` — frozen derived baseline.

## Certification boundary

This firewall can certify classification logic and prevent prohibited promotion paths. It cannot close the baseline case's pan/zoom or independent-source evidence without additional controlled observations of the same ground target.
