# SATIM Calibration Program

SATIM is split into five independently calibratable layers. L1-L4 cover FR24 screenshot intelligence. L5 covers satellite/aerial imagery artifact discrimination and should not block base FR24 screenshot readiness.

## Layers

| Layer | Module | Domain | Gate |
|---|---|---|---|
| L1 | `fr24.calibration.l1_segmenter_calibration` | FR24 UI geometry | Map bbox captures route pixels and excludes panel text |
| L2 | `fr24.calibration.l2_route_calibration` | FR24 route-color extraction | Recall/FPR tuning for route colors and blank tiles |
| L3 | `fr24.calibration.l3_ocr_scoring` | Vision/OCR metadata | Field-level exact-match scoring against ground truth |
| L4 | `fr24.calibration.l4_registry_audit` | Operator/mission registry | Registry coverage and onboarding candidate audit |
| L5 | `fr24.calibration.l5_tile_seam_shadow_calibration` | Satellite/aerial imagery | Tile seam vs cloud/shadow/terrain/ground-feature discrimination |

## Commands

```bash
python -m fr24.calibration.l1_segmenter_calibration --input data/fr24/screenshots --output reports/satim/l1_segmenter_report.json
python -m fr24.calibration.l2_route_calibration --input data/fr24/screenshots --blank-input data/fr24/blank_tiles --output reports/satim/l2_route_report.json
python -m fr24.calibration.l3_ocr_scoring --ground-truth data/fr24/ground_truth/satim_l3_ground_truth.csv --predictions reports/fr24/vision_ingest_output.json --output reports/satim/l3_ocr_score_report.json
python -m fr24.calibration.l4_registry_audit --fr24-csv data/fr24/exports/fr24_export.csv --output reports/satim/l4_registry_audit.json
python -m fr24.calibration.l5_tile_seam_shadow_calibration --candidates-csv data/satim/l5_candidates.csv --output reports/satim/l5_tile_seam_shadow.json
python -m fr24.calibration.run_satim_calibration --l1 reports/satim/l1_segmenter_report.json --l2 reports/satim/l2_route_report.json --l3 reports/satim/l3_ocr_score_report.json --l4 reports/satim/l4_registry_audit.json --l5 reports/satim/l5_tile_seam_shadow.json --output reports/satim/calibration_report.json
```

## Readiness rules

- Missing `calibration_report.json` remains a degraded readiness warning in the PRII engine.
- L1, L2, or L3 degraded means SATIM is degraded for batch FR24 analysis.
- L4 degraded means partial readiness unless L1-L3 are already degraded.
- L5 missing or degraded is partial for base FR24 readiness, but blocking for satellite/aerial imagery artifact workflows.
- A full L1-L5 pass yields `READY_FOR_BATCH_ANALYSIS`.

## L5 decision posture

L5 should never verify a tile seam from one still image alone. It scores likelihoods:

- `tile_seam_likelihood`
- `cloud_shadow_likelihood`
- `terrain_shadow_likelihood`
- `persistent_ground_feature_likelihood`

Promotion rule:

```text
probable tile seam = straight boundary + radiometric discontinuity + non-persistence across dates + no terrain alignment
probable ground feature = multi-date persistence + infrastructure/landcover alignment + low cloud/shadow intersection
```

## PRII compatibility

`fr24.calibration.readiness_adapter` converts a SATIM `schema_version: satim.calibration.v1` report into the legacy PRII calibration fields:

- `status`
- `baseline_mode`
- `calibration_flags`
- `candidate_count`

This preserves compatibility while carrying the richer SATIM layer payload.
