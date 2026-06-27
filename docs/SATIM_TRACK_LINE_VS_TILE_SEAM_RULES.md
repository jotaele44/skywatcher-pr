# SATIM Track-Line vs Tile-Seam vs UI-Overlay Rules

## Purpose

SATIM must separate three visually similar classes before any imagery-derived candidate is promoted:

1. FR24 track-line overlays.
2. FR24/UI overlay artifacts.
3. Satellite or aerial imagery tile seams.

This document defines Phase 1 decision rules for the SATIM visual and tile artifact ledgers.

## Rule Matrix

| Signal | Track line | UI overlay | Tile seam | Ground feature |
|---|---:|---:|---:|---:|
| Matches FR24 route color/opacity | High | Low/Medium | Low | Low |
| Anchored to aircraft route geometry | High | Low | Low | Low |
| Anchored to panel, label, icon, range ring, or UI element | Low | High | Low | Low |
| Axis-aligned or tile-grid aligned | Low/Medium | Medium | High | Variable |
| Radiometric discontinuity across image pixels | Low | Low | High | Variable |
| Screen-locked across frames while aircraft/platform moves | High | High | High | Low |
| Persists across imagery dates | Low | Low | Low | High |
| Aligns to road/building/airport/parcel geometry | Variable | Low | Low | High |

## Promotion Rules

### Probable track line

Classify as `probable_track_line` when:

```text
track_line_overlap >= 0.70
AND route_color_match == true
AND geometry follows recorded FR24 route segment
AND radiometric_delta < 0.50
```

Decision: `suppress` unless a non-overlay source independently supports the same boundary.

### Probable UI overlay

Classify as `probable_ui_overlay` when:

```text
ui_overlay_overlap >= 0.70
OR ui_anchor_match == true
OR candidate intersects label box / panel / icon / range ring mask
```

Decision: `suppress` unless the same geometry remains after UI masks are removed.

### Probable tile seam

Classify as `probable_tile_seam` when:

```text
straightness >= 0.85
AND radiometric_delta >= 0.55
AND screen_locked_score >= 0.70
AND multi_date_persistence < 0.35
AND terrain_shadow_likelihood < 0.55
AND persistent_ground_feature_likelihood < 0.55
```

Decision: `review` or `accepted_artifact`; never promote to structural signal from one still image.

### Probable ground feature

Classify as `probable_ground_feature` when:

```text
multi_date_persistence >= 0.65
AND max(road_alignment, building_alignment, airport_alignment, parcel_alignment) >= 0.50
AND ui_overlay_overlap < 0.35
AND track_line_overlap < 0.35
```

Decision: `cross_source_required` unless corroborated by independent GIS or imagery sources.

## Contradiction Flags

| Flag | Meaning |
|---|---|
| `track_line_color_conflict` | Candidate looks like a route line but color/opacity does not match known FR24 route styling. |
| `ui_mask_conflict` | Candidate intersects UI mask but also appears in raw imagery. |
| `single_still_seam_claim` | Candidate was promoted as seam/structure using only one image. |
| `persistent_tile_claim` | Candidate was called a tile seam despite multi-date persistence. |
| `infrastructure_false_rejection` | Candidate was rejected only because infrastructure alignment exists. |

## Output Contract

Every classified candidate should produce:

- one `satim.visual_ledger.v1` row;
- zero or one `satim.tile_artifact_ledger.v1` row;
- contradiction flags when evidence conflicts;
- a review state before any downstream promotion.
