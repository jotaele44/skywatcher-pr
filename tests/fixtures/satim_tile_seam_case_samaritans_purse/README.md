# SATIM Tile Seam Calibration Fixture: Samaritan's Purse 001

## Purpose

This fixture records a negative-control SATIM case for separating probable map-provider tile seams from physical ground features or anomalous signatures.

## Privacy mode

This fixture is derived-only. It must not contain:

- raw coordinates
- EXIF metadata
- full-resolution property imagery
- identifiable property context beyond abstract object anchors

## Derived observations

- A tonal discontinuity crosses unrelated land-cover classes.
- The discontinuity persists across zoomed frames.
- The seam-like boundary intersects vegetation, field texture, a road edge, a small building/roof area, and vehicle anchors.
- The boundary does not cleanly follow road, roof, drainage, terrain, or shadow geometry.

## Locked label

```yaml
case_id: SATIM_TILE_SEAM_SAMARITANS_PURSE_001
primary_label: TILE_SEAM_PROBABLE
artifact_confidence: MEDIUM_HIGH
ground_feature_confidence: LOW
uap_relevance: NEGATIVE_CONTROL
privacy_mode: DERIVED_FIXTURE_ONLY
raw_coordinate_release: false
```

## Calibration use

Use this case to regression-test artifact discrimination before promoting any high-zoom basemap signature to a ground-feature or anomaly queue.
