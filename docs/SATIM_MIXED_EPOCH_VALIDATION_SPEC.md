# SATIM Mixed-Epoch Validation Spec

## Purpose

SATIM L5 must never establish renderer-tile identity, source-mosaic identity, or a physical-ground identity from one still image or from multi-date persistence alone. Phase 1 adds a repeatable validation contract for comparing the same candidate across imagery dates, render states, and independent sources while preserving causal origin as a separate, explicitly gated axis.

## Required Inputs

| Input | Required | Description |
|---|---:|---|
| `visual_id` | Yes | SATIM visual-ledger candidate ID. |
| `source_image_id` | Yes | Current image or screenshot identifier. |
| `capture_datetime_utc` | Yes | Timestamp for the current source image. |
| `imagery_epoch` | Preferred | Provider or capture epoch when available. |
| `geometry` | Yes | Candidate point, line, or polygon. |
| `comparison_images` | Yes for validation | Same AOI from different capture/render dates. Same-ground identity must be established before comparison. |
| `feature_scores` | Yes | SATIM L0-L4 feature scores. |
| `provider_metadata` | Preferred | Tile version, zoom, basemap, imagery product, or source-mosaic metadata. |

## Epoch Classes

| Class | Definition | Default disposition |
|---|---|---|
| `same_epoch` | Same provider imagery date and tile generation. | Use for render consistency only. |
| `near_epoch` | Different render/date but insufficient seasonal separation. | Review. |
| `cross_epoch` | Meaningfully different imagery date, provider, or capture cycle after same-ground binding. | Valid comparison. |
| `unknown_epoch` | Date/provider unavailable. | Review; do not promote. |

## Validation Logic

### Imagery-seam observation

A candidate may retain the legacy observation label `probable_tile_seam` when visual evidence supports a boundary, but this label is **not** a causal tile-edge identity. Screen lock is not a positive provider-tile criterion.

```text
straightness >= 0.85
AND radiometric_delta >= 0.55
AND terrain_shadow_likelihood < 0.55
AND track_line_overlap < 0.55
AND ui_overlay_overlap < 0.55
```

Causal adjudication then occurs separately:

```text
SCREEN_FIXED under pan
    -> VIEWPORT_COMPOSITING_ARTIFACT candidate

DISPLAY_TILE_EDGE = PASS
    -> requires provider_tile_grid_binding

SOURCE_MOSAIC_CUTLINE = PROVISIONAL
    -> ground_fixed_under_pan
    AND adjacent_zoom_ground_persistence
    AND not provider_tile_grid_bound
    AND no independent physical-ground binding

SOURCE_MOSAIC_CUTLINE = PASS
    -> requires authoritative source_mosaic_metadata_binding
```

### Mixed-epoch artifact

A candidate may be marked `mixed_epoch_artifact` when:

```text
radiometric_delta >= 0.55
AND a same-ground cross-epoch comparison is established
AND adjacent sides show different seasonal, construction, cloud, shadow, or landcover states
AND the observed boundary disappears or shifts in the cross-epoch comparison
```

A visible boundary resembling a mosaic edge is discovery evidence only unless provider/source metadata independently binds that origin.

### Persistent ground-feature candidate

Multi-date persistence may create `persistent_ground_feature_candidate`, not physical-ground identity:

```text
multi_date_persistence >= 0.65
AND geometry remains stable across certified same-ground cross-epoch imagery
AND track_line_overlap < 0.35
AND ui_overlay_overlap < 0.35
```

GIS alignment strengthens or explains the candidate but does not itself establish identity.

`PHYSICAL_GROUND_FEATURE = PASS` requires an **independent physical-ground binding**. Persistence, GIS proximity/alignment, same category, or deterministic ranking are insufficient by themselves.

## Required Ledger Fields

The mixed-epoch pass should populate:

- `imagery_epoch`
- `source_dates_compared`
- `multi_date_persistence`
- `contradiction_flags`
- `cross_source_refs`
- `review_state`

Where an origin-bearing consumer is involved, it must additionally preserve:

- `resolved_origin`
- `origin_state`
- the complete `origin_candidates` set or equivalent origin-candidate ledger

An unresolved origin must not carry positive causal confidence.

## Review Gates

| Condition | Gate |
|---|---|
| Only one still image available | `cross_source_required` |
| Same-ground identity not established | `blocked` |
| Epoch metadata missing | `review` |
| Candidate changes with provider/date | `mixed_epoch_artifact` or imagery-seam observation candidate |
| Candidate persists across independent dates | `persistent_ground_feature_candidate`; independent ground binding still required |
| FR24 track/UI evidence present | suppress or review before imagery classification |
| Provider tile-grid binding absent | never promote `DISPLAY_TILE_EDGE` |
| Source-mosaic metadata absent | never promote `SOURCE_MOSAIC_CUTLINE` beyond `PROVISIONAL` |

## Minimum Phase 1 Test Fixtures

1. Single-image seam candidate: must not establish causal origin.
2. Screen-fixed pan candidate: must favor viewport compositing, not display-tile identity.
3. Provider-grid-bound candidate: may establish display-tile identity only through the grid binding.
4. Multi-date disappearing boundary: may classify as mixed-epoch artifact without assuming source-mosaic identity.
5. Multi-date persistent road/building edge: must remain `persistent_ground_feature_candidate` until independently bound.
6. UI/track overlap candidate: must suppress before imagery promotion.
7. Coastal crossing candidate: must require cross-epoch comparison before structural interpretation.
