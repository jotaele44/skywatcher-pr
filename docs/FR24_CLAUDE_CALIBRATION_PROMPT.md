# FR24 Claude Calibration Prompt

## Status

This prompt is the pre-sweep calibration gate for the FR24 screenshot database. It must be run before any full screenshot sweep.

## Claude Prompt

```text
You are working in the skywatcher-pr FR24 visual-analysis repository.

Mission: run a calibration-first tile/anomaly/ground-candidate pilot before any full screenshot database sweep. Do not begin a full sweep until the calibration gate passes.

Authoritative registry files:
- data/reference/fr24_allowed_enum_registry.json
- data/reference/fr24_pre_contract_parameter_universe.json
- data/reference/fr24_parameter_family_queue.json
- fr24_allowed_enums.py
- fr24_parameter_contracts.py
- tests/test_fr24_allowed_enums.py
- tests/test_fr24_parameter_contracts.py

Required pipeline order:
1. provenance
2. privacy
3. tile_suppression
4. ground_context
5. infrastructure_context
6. recurrence
7. export

Critical rule: tile_suppression must run before ground_context.

Tile-analysis v2 signal groups to run before ground interpretation:
- tile_analysis
- seam_anomaly_detection
- tile_artifact_suppression
- roi_mask_analysis
- seam_geometry_v2
- tone_texture_v2
- geometry_displacement_v2
- blur_smear_canopy
- mixed_epoch_detection
- dem_terrain_mismatch
- ui_route_annotation_suppression
- shadow_canopy_confusion
- seam_context_recurrence
- tile_score_breakdown
- calibration_expected_outputs

Required calibration behavior:
1. Load the registry and validate it.
2. Inventory calibration screenshots.
3. Hash every image.
4. Classify ROI-level masks before whole-image interpretation.
5. Suppress or review-gate regions affected by UI overlays, user annotations, FR24 route lines, Apple Maps controls, map labels, map symbols, tile seams, severe blur, directional smear, low-resolution canopy, shadow confusion, mixed epoch, DEM/terrain mismatch, or compression artifacts.
6. Preserve clean ground ROIs even when another part of the same screenshot is suppressed.
7. Write calibration outputs before any full sweep.

Required outputs:
- exports/visual/calibration/tile_anomaly_calibration_inventory.csv
- exports/visual/calibration/tile_anomaly_calibration_roi_labels.csv
- exports/visual/calibration/tile_anomaly_calibration_expected_outputs.jsonl
- exports/visual/calibration/tile_anomaly_calibration_actual_outputs.jsonl
- exports/visual/calibration/tile_anomaly_calibration_mismatch_report.csv
- exports/visual/calibration/tile_anomaly_calibration_report.md

Every ROI output row must include:
- calibration_fixture_id
- calibration_wave_id
- screenshot_id
- image_path
- image_sha256
- roi_id
- roi_type
- roi_bbox_screen
- roi_ground_readability_score
- roi_suppression_status
- artifact_type
- artifact_severity
- suppression_reason
- expected_artifact_type
- expected_artifact_severity
- expected_suppression_status
- expected_ground_candidate_type
- actual_ground_candidate_type
- calibration_match_status
- calibration_error_type
- interpretation_guardrail

Allowed interpretation guardrails:
- artifact_only
- visual_candidate_only
- contextual_correlation_only
- recurrence_supported_only

Forbidden labels:
- confirmed_hidden_access
- confirmed_tunnel
- confirmed_ilap
- confirmed_illegal_activity
- confirmed_restricted_site
- confirmed_covert_site

Acceptance gate:
- artifact suppression accuracy must be at least 90%;
- no UI overlay may be promoted to a ground feature;
- no FR24 route line may be promoted to a road, seam, or ground feature;
- no user annotation may be promoted to ground evidence;
- clean pools, roads, buildings, clearings, and waterbody candidates must remain detectable when readable;
- ambiguous or partially obscured ROIs must be review-gated, not overclassified;
- every screenshot must have a processing state;
- every skipped image must have a reason.

If the calibration gate fails, stop. Report the failure and recommended fixes. Do not run the full database sweep.

If the calibration gate passes, proceed only to a deterministic pilot batch, not the full sweep:
- first 25 readable screenshots sorted by path;
- write outputs;
- validate sidecars;
- report mismatch and failure rates.

Only after the pilot batch passes should the full database sweep be allowed.

All outputs are candidate or artifact evidence only. Do not infer ownership, function, wrongdoing, hidden access, tunnel presence, restricted access, or operational purpose from screenshots alone.
```

## Operator Note

This prompt intentionally prioritizes suppression, ROI isolation, and calibration accuracy before extraction volume. Its purpose is to prevent tile/UI/annotation artifacts from contaminating later ground-context and recurrence layers.
