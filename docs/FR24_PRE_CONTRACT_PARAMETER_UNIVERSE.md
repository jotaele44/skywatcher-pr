# FR24 Pre-Contract Parameter Universe

## Status

Locked before `05_PARAMETER_CONTRACT_LAYER`.

This document records the final pre-contract additions requested before enforcing the parameter-contract layer.

## Purpose

The pre-contract universe adds support/control families plus tile-analysis and seam-anomaly detection parameters. These families prevent later registry ambiguity by standardizing origin, absence, deduplication, review, interpretation, environmental context, visual artifacts, scoring metadata, tile provenance, and seam artifacts.

## Support Families

| Family | Purpose |
|---|---|
| `parameter_origin` | Track why a parameter exists and what vector added it |
| `feature_presence_absence` | Standardize present/absent/uncertain/obscured/not-reviewed states |
| `spatial_index_dedup` | Support grid IDs, tile IDs, duplicate groups, and recurrence-safe deduplication |
| `review_triage` | Standardize review priority and blocker fields |
| `interpretation_guardrails` | Prevent visual candidates from being overstated as proof |
| `environmental_context` | Track season, rain/drought context, canopy, shadows, and sun-angle issues |
| `visual_artifact_control` | Track UI overlays, compression, blur, annotations, map labels, and tile artifacts |
| `scoring_model_metadata` | Track model ID/version, score inputs, weights, thresholds, and penalty fields |

## Tile Analysis Parameter Stack

The `tile_analysis` family tracks map tile provenance and quality:

```text
tile_id
tile_provider
tile_source_url_hash
tile_zoom
tile_x
tile_y
tile_bounds_wgs84
tile_capture_status
tile_load_status
tile_resolution_px
tile_pixel_density_estimate
tile_timestamp_source
tile_age_class
tile_match_confidence
tile_neighbor_count
tile_neighbor_ids
tile_edge_north_id
tile_edge_south_id
tile_edge_east_id
tile_edge_west_id
tile_visual_quality_score
tile_artifact_flag
tile_artifact_type
tile_review_status
```

## Seam Anomaly Detection Parameters

The `seam_anomaly_detection` family tracks basemap seams and tile artifacts:

```text
seam_visible_flag
seam_type
seam_orientation
seam_line_screen_x1
seam_line_screen_y1
seam_line_screen_x2
seam_line_screen_y2
seam_width_px
seam_length_px
seam_offset_px
seam_color_discontinuity_score
seam_texture_discontinuity_score
seam_label_cutoff_flag
seam_road_discontinuity_flag
seam_hydro_discontinuity_flag
seam_building_discontinuity_flag
seam_vegetation_discontinuity_flag
duplicated_feature_across_seam_flag
missing_feature_gap_flag
tile_boundary_overlap_flag
tile_loading_artifact_flag
basemap_stitching_artifact_flag
seam_false_positive_risk
seam_anomaly_score
seam_anomaly_class
seam_review_status
seam_interpretation_note
```

## Interpretation Rule

Seam parameters identify map/tile artifacts only. They must not be interpreted as physical ground features without independent confirmation.

## Machine-Readable Manifest

```text
data/reference/fr24_pre_contract_parameter_universe.json
```

## Next Step

Proceed to `05_PARAMETER_CONTRACT_LAYER` and enforce these families through the same contract mechanism as visual, POI, TLT, and waterbody parameters.
