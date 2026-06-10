# FR24 Selected Candidates Export and Dashboard Queue

## Purpose

This layer packages FR24 OCR selected candidate rows for downstream Spiderweb
consumers and produces a review-first dashboard queue. All outputs remain
candidate or review records. No event is confirmed by this layer.

It adds:

1. `fr24/selected_export.py` — writes a curated CSV, a full-fidelity JSONL, an
   export summary, and a source manifest extension from
   `fr24_event_candidates_selected.csv`.
2. `fr24/dashboard_queue.py` — merges review-gated rows from selection,
   deduplication, fusion, and OCR error queues into a ranked dashboard queue.

## Export

Run:

```bash
python fr24/selected_export.py \
  --selected-csv data/_manifests/fr24_audit/fr24_event_candidates_selected.csv \
  --field-review-csv data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv \
  --duplicate-review-csv data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv \
  --ledger-csv data/_manifests/fr24_audit/fr24_batch_run_ledger.csv \
  --output-csv data/_manifests/fr24_audit/fr24_event_candidates_export.csv \
  --output-jsonl data/_manifests/fr24_audit/fr24_event_candidates_export.jsonl \
  --summary-json data/_manifests/fr24_audit/fr24_export_summary.json \
  --source-manifest-json data/_manifests/fr24_audit/fr24_source_manifest_extension.json
```

### Inputs

| File | Purpose |
|---|---|
| `fr24_event_candidates_selected.csv` | Selected rows from `fr24/field_select.py` |
| `fr24_field_selection_review_queue.csv` | Field-selection review rows (counted in summary) |
| `fr24_fused_duplicate_review_queue.csv` | Dedup review rows (counted in summary) |
| `fr24_batch_run_ledger.csv` | Joined for `source_batch_id` and `source_batch_finished_at` per `image_path` |

### Outputs

| File | Purpose |
|---|---|
| `fr24_event_candidates_export.csv` | Curated columns for downstream tooling |
| `fr24_event_candidates_export.jsonl` | Full-fidelity per-row record |
| `fr24_export_summary.json` | Row counts and label distributions |
| `fr24_source_manifest_extension.json` | Source manifest extension with input/output paths and upstream version stamps |

### Exported columns

Each exported row carries:

- `candidate_id`, `image_path`, `image_name`
- The 14 selected fields and their `<field>_selected_source` columns:
  - `callsign_or_label`, `operator`, `aircraft_type`, `registration`,
    `origin_code`, `destination_code`, `barometric_altitude_ft`,
    `ground_speed_mph`, `flight_status`, `elapsed_departed`,
    `elapsed_arrived`, `playback_date`, `playback_time`, `playback_timezone`
- `review_status`, `selection_status`, `dedup_status`
- `confirmation_status` — always `not_confirmed` (rewritten on export)
- `selected_field_disagreements`, `missing_selected_fields`,
  `conflict_count`, `whole_confidence`, `region_confidence`
- `source_csv_path`, `source_batch_id`, `source_batch_finished_at`
- `export_version` (`fr24_selected_export_v0.1.0`)
- Provenance versions preserved from upstream: `fusion_version`,
  `field_select_version`, `dedup_version`, `parser_version`

### Defense-in-depth label gate

If a row's `confirmation_status`, `dedup_status`, `selection_status`, or
`review_status` matches a prohibited label, the row is dropped from the export
and counted in `prohibited_label_dropped` in the summary. The current pipeline
does not emit these labels, but the gate is enforced anyway.

## Dashboard queue

Run:

```bash
python fr24/dashboard_queue.py \
  --selected-csv data/_manifests/fr24_audit/fr24_event_candidates_selected.csv \
  --field-review-csv data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv \
  --duplicate-review-csv data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv \
  --ocr-error-csv data/_manifests/fr24_audit/fr24_batch_error_queue.csv \
  --output-csv data/_manifests/fr24_audit/fr24_dashboard_review_queue.csv \
  --summary-json data/_manifests/fr24_audit/fr24_dashboard_queue_summary.json
```

`fr24_batch_error_queue.csv` is loaded only if present (it is produced by
`fr24/batch_run.py`). A missing OCR-error file is not an error.

### Ranking

| Tier | Source | Base score |
|---|---|---|
| 1 | Field disagreement (`selection_status == field_disagreement_review`) | 100 |
| 2 | Fusion conflict (`review_status == fusion_conflict_review`) | 80 |
| 3 | Manual review required (selection review rows or `review_status == manual_review_required`) | 60 |
| 4 | Duplicate review (`fr24_fused_duplicate_review_queue.csv` rows) | 40 |
| 5 | Metadata gap (`review_status == metadata_gap`) | 25 |
| 6 | OCR failure (`region_ocr_failed`, `region_low_text_review`, `low_text_review`, batch ledger `status == failed`) | 15 |

Score adjustments: `+5` per `conflict_count` (capped at `+20`), and `+5` if
`selected_field_disagreements` is non-empty. Final sort:
`(-priority_score, priority_tier, image_name)`. Within a single source the
queue is deduplicated by `(image_path, queue_source)`.

### Queue lifecycle

The queue is written with `queue_status = dashboard_review_open` on every row.
Dashboard operators may transition rows through these allowed values:

- `dashboard_review_open`
- `dashboard_review_deferred`
- `dashboard_review_rejected`
- `dashboard_review_accepted_after_manual_review`

## Labels

### Allowed

- `selected_candidate`
- `selected_with_review_required`
- `field_disagreement_review`
- `dedup_duplicate_review`
- `manual_review_required`
- `not_confirmed`
- `dashboard_review_open`
- `dashboard_review_deferred`
- `dashboard_review_rejected`
- `dashboard_review_accepted_after_manual_review`

### Prohibited

- `confirmed`
- `confirmed_aircraft_event`
- `confirmed_anomaly`
- `confirmed_route`
- `verified_event`
- `validated_aircraft_event`

## Recommended local validation

```bash
python -m py_compile fr24/selected_export.py fr24/dashboard_queue.py

python fr24/selected_export.py
python fr24/dashboard_queue.py
```

## Next step

After validation, wire the dashboard review queue into the Spiderweb operator
dashboard so a reviewer can work the highest-priority items first.
