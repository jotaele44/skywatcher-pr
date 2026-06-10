# FR24 Dedup and Field Selection

## Purpose

This layer hardens the FR24 fused OCR candidate pipeline after batch execution.

It adds:

1. `fr24/fused_dedup.py` — removes duplicate fused candidate rows across one or more fused CSVs.
2. `fr24/field_select.py` — creates review-gated selected candidate fields while preserving whole-image and region source values.

These tools keep outputs as candidate records.

## Deduplication

Run:

```bash
python fr24/fused_dedup.py \
  --input-csv data/_manifests/fr24_audit/fr24_fused_event_candidates.csv \
  --output-csv data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv \
  --duplicates-csv data/_manifests/fr24_audit/fr24_fused_duplicate_review_queue.csv \
  --summary-json data/_manifests/fr24_audit/fr24_fused_dedup_summary.json
```

Multiple fused CSVs can be supplied by repeating `--input-csv`.

Dedup key priority:

1. `image_path`
2. `image_name`
3. `candidate_id`

Outputs:

| File | Purpose |
|---|---|
| `fr24_fused_event_candidates_deduped.csv` | One preferred row per image key |
| `fr24_fused_duplicate_review_queue.csv` | Duplicate rows routed to review |
| `fr24_fused_dedup_summary.json` | Counts and dedup diagnostics |

## Field selection

Run:

```bash
python fr24/field_select.py \
  --input-csv data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv \
  --output-csv data/_manifests/fr24_audit/fr24_event_candidates_selected.csv \
  --review-csv data/_manifests/fr24_audit/fr24_field_selection_review_queue.csv \
  --summary-json data/_manifests/fr24_audit/fr24_field_selection_summary.json
```

Selection rules:

- Preserve `<field>_wi` and `<field>_region` values from fusion.
- If both values exist and disagree, route to `field_disagreement_review`.
- Prefer `right_panel` for aircraft detail fields when values agree.
- Prefer `bottom_timeline` for playback fields when values agree.
- Otherwise prefer the higher-confidence source when both agree.

Selected fields:

```text
callsign_or_label
operator
aircraft_type
registration
origin_code
destination_code
barometric_altitude_ft
ground_speed_mph
flight_status
elapsed_departed
elapsed_arrived
playback_date
playback_time
playback_timezone
```

## Labels

Allowed output labels:

- `dedup_kept_primary`
- `dedup_duplicate_review`
- `selected_candidate`
- `selected_with_review_required`
- `field_disagreement_review`
- `not_confirmed`

## Recommended local validation

```bash
python -m py_compile fr24/fused_dedup.py fr24/field_select.py

python fr24/fused_dedup.py \
  --input-csv data/_manifests/fr24_audit/fr24_fused_event_candidates.csv

python fr24/field_select.py \
  --input-csv data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv
```

## Next step

After validation, connect selected candidates to the wider Spiderweb export layer and build a dashboard-facing review queue.
