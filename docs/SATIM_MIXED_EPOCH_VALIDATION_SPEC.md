# SATIM Mixed-Epoch Validation Spec

## Purpose

SATIM L5 should never verify a tile seam or structural signal from one still image alone. Phase 1 adds a repeatable validation contract for comparing the same candidate across imagery dates, render states, and independent sources.

## Required Inputs

| Input | Required | Description |
|---|---:|---|
| `visual_id` | Yes | SATIM visual-ledger candidate ID. |
| `source_image_id` | Yes | Current image or screenshot identifier. |
| `capture_datetime_utc` | Yes | Timestamp for the current source image. |
| `imagery_epoch` | Preferred | Provider or capture epoch when available. |
| `geometry` | Yes | Candidate point, line, or polygon. |
| `comparison_images` | Yes for validation | Same AOI from different capture/render dates. |
| `feature_scores` | Yes | SATIM L0-L4 feature scores. |
| `provider_metadata` | Preferred | Tile version, zoom, basemap, or imagery product metadata. |

## Epoch Classes

| Class | Definition | Default disposition |
|---|---|---|
| `same_epoch` | Same provider imagery date and tile generation. | Use for render consistency only. |
| `near_epoch` | Different render/date but insufficient seasonal separation. | Review. |
| `cross_epoch` | Meaningfully different imagery date, provider, or capture cycle. | Valid comparison. |
| `unknown_epoch` | Date/provider unavailable. | Review; do not promote. |

## Validation Logic

### Probable tile seam

A candidate may be marked `probable_tile_seam` when:

```text
straightness >= 0.85
AND radiometric_delta >= 0.55
AND screen_locked_score >= 0.70
AND non_persistence_across_cross_epoch_images == true
AND terrain_alignment < 0.55
AND infrastructure_alignment < 0.65
```

### Mixed-epoch artifact

A candidate may be marked `mixed_epoch_artifact` when:

```text
radiometric_delta >= 0.55
AND boundary follows a tile or mosaic edge
AND adjacent sides show different seasonal, construction, cloud, shadow, or landcover states
AND the edge disappears or shifts in a cross-epoch comparison
```

### Persistent ground feature

A candidate may be marked `probable_ground_feature` when:

```text
multi_date_persistence >= 0.65
AND geometry remains stable across cross-epoch imagery
AND at least one GIS layer explains the feature
AND track_line_overlap < 0.35
AND ui_overlay_overlap < 0.35
```

## Required Ledger Fields

The mixed-epoch pass should populate:

- `imagery_epoch`
- `source_dates_compared`
- `multi_date_persistence`
- `contradiction_flags`
- `cross_source_refs`
- `review_state`

## Review Gates

| Condition | Gate |
|---|---|
| Only one still image available | `cross_source_required` |
| Epoch metadata missing | `review` |
| Candidate changes with provider/date | `mixed_epoch_artifact` or `probable_tile_seam` |
| Candidate persists across independent dates | `probable_ground_feature` candidate, still requiring GIS corroboration |
| FR24 track/UI evidence present | suppress or review before imagery classification |

## Minimum Phase 1 Test Fixtures

1. Single-image seam candidate: must not promote beyond `review`.
2. Multi-date disappearing boundary: can classify as tile/mixed-epoch artifact.
3. Multi-date persistent road/building edge: should classify as ground feature.
4. UI/track overlap candidate: must suppress before imagery promotion.
5. Coastal crossing candidate: must require cross-epoch comparison before structural interpretation.
