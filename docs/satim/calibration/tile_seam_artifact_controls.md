# SATIM Tile Seam Artifact Controls

## Vector

`SATIM_TILE_SEAM_CALIBRATION_PR_BUILD`

## Objective

Add a negative-control calibration pattern for high-zoom basemap captures where a tonal discontinuity is more consistent with map-provider tile stitching than with a physical ground feature.

## Classification standard

A case may be labeled `TILE_SEAM_PROBABLE` when the derived evidence satisfies all core conditions:

1. The tonal break crosses unrelated land-cover classes.
2. The boundary persists across zoomed frames or adjacent captures.
3. The split does not follow road, roof, terrain, drainage, or plausible shadow geometry.
4. Object anchors remain spatially consistent across both tonal zones.

## Negative-control role

This label is not an anomaly-positive result. It is a guardrail case used to prevent SATIM from over-promoting imagery artifacts into ground-feature, route, or UAP-adjacent queues.

## Case: SATIM_TILE_SEAM_SAMARITANS_PURSE_001

| Field | Value |
|---|---|
| Source type | FR24 / Apple Maps screen capture |
| Primary label | `TILE_SEAM_PROBABLE` |
| Artifact confidence | `MEDIUM_HIGH` |
| Ground-feature confidence | `LOW` |
| UAP relevance | `NEGATIVE_CONTROL` |
| Privacy mode | `DERIVED_FIXTURE_ONLY` |

## Privacy constraint

The public repository must not receive raw coordinates, EXIF, full-resolution property imagery, or identifiable local context unless intentionally approved. The fixture ledger stores derived boolean evidence only.

## Operational use

Run the targeted regression test before expanding SATIM classifiers that evaluate:

- orthophoto or basemap texture discontinuities
- high-zoom FR24 / Apple Maps screen captures
- tonal seams crossing multiple object classes
- false-positive ground-feature candidates

```bash
pytest tests/test_satim_tile_seam_classifier.py
```

## Confidence and blind spot

The case supports `TILE_SEAM_PROBABLE` at medium-high artifact confidence. It does not independently verify the source map provider tile boundary because raw georeferencing is intentionally excluded from the public fixture.
