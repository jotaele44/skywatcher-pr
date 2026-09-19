# IMG_5369 SATIM Fixture Contract

## Scope

Satellite/basemap visual analysis only. Aircraft and track analysis are NONAPPLICABLE.

## Frozen source

- filename: `IMG_5369.jpeg`
- SHA-256: `fca95e9dc86476a063583df9691d77f0cb1076cc2bc9a32fa56a8767860e77ad`
- screenshot timestamp: `2026-09-17 11:58:11`
- imagery acquisition epoch: UNKNOWN

## Expected single-frame behavior

The image contains a bright cloud mass adjacent to an elongated dark radiometric region across mountainous terrain. The single-frame visual frontend may emit one or more visual candidates, but MUST NOT certify causal origin.

Required safeguards:

- `screen_locked_score = 0` unless established from pan behavior;
- `ground_fixed_score = 0` unless established from repeat/pan registration;
- `provider_tile_grid_binding_score = 0` unless independently bound;
- `adjacent_zoom_ground_persistence_score = 0` unless measured;
- `source_mosaic_metadata_binding_score = 0` unless source metadata binds the cutline;
- `independent_ground_feature_binding_score = 0` unless independently established;
- strict L5 `origin_state` MUST NOT be `PASS` from this single frame alone;
- `resolved_origin` MUST remain `UNRESOLVED` without additional evidence.

## Regression purpose

This is a negative origin-promotion fixture. It tests whether a cloud/shadow-like single-frame radiometric feature can be detected without being silently promoted to:

- `DISPLAY_TILE_EDGE`
- `SOURCE_MOSAIC_CUTLINE`
- `PHYSICAL_GROUND_FEATURE`

Repeat imagery, coordinate behavior, terrain controls, provider-grid evidence, or independent physical binding are required for promotion.
