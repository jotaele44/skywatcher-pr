# SATIM Engine Protocol Interface

The SATIM engine interface is the operator-facing contract for running `skywatcher-pr` SATIM analysis on a new input bundle. It wraps the existing L1-L5 calibration modules behind one manifest-driven command and emits a deterministic run bundle.

## Command

```bash
python -m fr24.satim_engine run \
  --manifest path/to/satim_manifest.yaml \
  --output reports/satim/runs/<run_id>
```

Autodetect mode is also supported:

```bash
python -m fr24.satim_engine run \
  --input path/to/input_dir_or_zip \
  --output reports/satim/runs/<run_id>
```

## Manifest contract

```yaml
schema_version: satim.engine.input.v1
run_id: moca_fr24_2026_07_02_test
input_profile: fr24_screenshot_batch

inputs:
  screenshots_dir: data/satim_runs/moca/screenshots
  annotations_json: data/satim_runs/moca/annotations.json
  blank_screenshots_dir: data/satim_runs/moca/blanks
  ground_truth_csv: data/satim_runs/moca/ground_truth.csv
  predictions_json: data/satim_runs/moca/predictions.json
  fr24_csv: data/satim_runs/moca/fr24_export.csv
  l5_candidates_csv: data/satim_runs/moca/l5_candidates.csv
  calibration_set_dir: data/satim_calibration/moca_fr24_2025

options:
  min_route_pixels: 8
  strict: false
  include_l5: true
  export_legacy_readiness: true

outputs:
  run_dir: reports/satim/runs/moca_fr24_2026_07_02_test
```

## Layer policy

| Layer | Input | Status policy |
|---|---|---|
| L1 UI segmenter | `screenshots_dir` | Required base layer |
| L2 route extractor | `screenshots_dir`, optional `blank_screenshots_dir` | Required base layer |
| L3 vision/OCR | `ground_truth_csv` and `predictions_json` | Required base layer |
| L4 aircraft intelligence | `fr24_csv` | Advisory layer |
| L5 tile seam/shadow | `l5_candidates_csv` | Advisory layer |

Missing L1-L3 inputs create blocking `MISSING` layer reports unless `strict: true`, in which case the run fails before report merge. Missing L4-L5 inputs are advisory and become recommended next actions.

## Standard autodetect layout

```text
input_root/
  screenshots/
  blanks/
  annotations.json
  ground_truth.csv
  predictions.json
  fr24_export.csv
  l5_candidates.csv
  calibration_set/
```

If `satim_manifest.yaml`, `satim_manifest.yml`, or `satim_manifest.json` exists in the input root, the runner uses it instead of autodetection.

## Output bundle

```text
reports/satim/runs/<run_id>/
  resolved_manifest.json
  provenance.json
  run_summary.json
  calibration_report.json
  legacy_readiness.json
  calibration_set_validation.json
  layers/
    l1_ui_segmenter.json
    l2_route_extractor.json
    l3_vision_ocr.json
    l4_aircraft_intelligence.json
    l5_tile_seam_shadow.json
```

`calibration_report.json` uses the existing `satim.calibration.v1` report model. `legacy_readiness.json` preserves the older PRII readiness contract for federation consumers.

## Safety posture

SATIM outputs are calibration and review artifacts. Candidate scores and layer statuses are not automated assertions about ground sites. Human review and cross-source validation remain required before any promotion.
