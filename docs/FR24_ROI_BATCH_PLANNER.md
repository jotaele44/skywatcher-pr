# FR24 Region OCR and Batch Planner

## Purpose

This layer extends the merged FR24 sidecar/OCR probe pipeline with two read-only tools:

1. `fr24/region_ocr.py` — region-based OCR over fixed FR24 screen areas.
2. `fr24/batch_plan.py` — deterministic full-corpus OCR batch planning.

Both tools preserve the candidate-only policy. They do not confirm aircraft events, anomalies, routes, or operational status.

## Region OCR

Run:

```bash
python fr24/region_ocr.py \
  --manifest data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv \
  --output-dir data/_manifests/fr24_audit \
  --limit 50
```

Default regions:

| Region | Purpose |
|---|---|
| `full_image` | Baseline whole-screen OCR |
| `right_panel` | Aircraft/flight detail panel |
| `top_bar` | App header and status context |
| `bottom_timeline` | Playback time/timeline context |
| `map_area` | Map labels and aircraft markers |

Outputs:

| File | Purpose |
|---|---|
| `fr24_region_ocr_results.jsonl` | Per-image, per-region OCR text |
| `fr24_region_ocr_summary.csv` | Per-region OCR status table |
| `fr24_region_ocr_summary.json` | Summary counts and low-text region diagnostics |

## Batch planning

Run:

```bash
python fr24/batch_plan.py \
  --manifest data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv \
  --output-dir data/_manifests/fr24_audit \
  --batch-size 250
```

Optional bounded run:

```bash
python fr24/batch_plan.py \
  --manifest data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv \
  --output-dir data/_manifests/fr24_audit \
  --batch-size 250 \
  --max-images 1000
```

Outputs:

| File | Purpose |
|---|---|
| `fr24_full_corpus_batch_plan.csv` | Ordered OCR batch plan |
| `fr24_full_corpus_batch_plan_summary.json` | Batch counts and source-status distribution |

## Batch priority order

The planner prioritizes:

1. strong matched primary sidecar rows,
2. reviewable matched primary rows,
3. weak matched primary rows,
4. metadata-gap rows,
5. remaining OCR-eligible rows.

## Conservative policy

All outputs are planning or OCR candidates only.

Allowed labels:

- `planned_candidate`
- `not_confirmed`
- `candidate_only_no_auto_confirmation`

No output from this layer may use:

- `confirmed`
- `confirmed_aircraft_event`
- `confirmed_anomaly`
- `confirmed_route`

## Next development step

After local validation, connect region OCR outputs to `fr24/ocr_parse.py` so the parser can compare full-image and region-specific OCR evidence before producing review queues.
