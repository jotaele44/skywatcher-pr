# FR24 Spiderweb Intake Adapter

## Purpose

This layer wires the FR24 OCR export JSONL
(`fr24_event_candidates_export.jsonl`) to the Spiderweb `flight_event` schema
so that dashboard-accepted candidates can flow into the main Spiderweb intake
pipeline.

It is a **candidate-only, no-auto-confirmation** layer. No record is confirmed
by this module; every intake record carries
`confirmation_status=not_confirmed` and
`intake_status=candidate_intake_ready`.

## Gate policy

Records pass to the intake queue only when **one** of the following is true:

| Field | Value |
|---|---|
| `selection_status` | `selected_candidate` |
| `dashboard_status` | `dashboard_review_accepted_after_manual_review` |

All other records are written to a hold queue with
`hold_reason=selection_status_not_passthrough` for later human review.

## Command

```bash
python fr24/spiderweb_adapter.py \
  --export-jsonl   data/_manifests/fr24_audit/fr24_event_candidates_export.jsonl \
  --output-jsonl   data/_manifests/fr24_audit/fr24_spiderweb_intake_candidates.jsonl \
  --hold-jsonl     data/_manifests/fr24_audit/fr24_spiderweb_hold_queue.jsonl \
  --summary-json   data/_manifests/fr24_audit/fr24_spiderweb_adapter_summary.json
```

## Inputs

| File | Purpose |
|---|---|
| `fr24_event_candidates_export.jsonl` | Full-fidelity export records from `fr24/selected_export.py` |

## Outputs

| File | Purpose |
|---|---|
| `fr24_spiderweb_intake_candidates.jsonl` | `flight_event`-compatible records ready for Spiderweb intake |
| `fr24_spiderweb_hold_queue.jsonl` | Records held pending review (not gate-eligible) |
| `fr24_spiderweb_adapter_summary.json` | Counts, policy assertion, and status distributions |

## Field mapping

### Required `flight_event` fields

| FR24 export field | `flight_event` field | Notes |
|---|---|---|
| `candidate_id` | `flight_id` | Falls back to `fr24::{image_name}` if blank |
| `callsign_or_label` | `callsign` | — |

### Optional `flight_event` fields

| FR24 export field | `flight_event` field | Transform |
|---|---|---|
| `aircraft_type` | `aircraft_type` | Passed through |
| `operator` | `operator` | Passed through |
| `origin_code` | `origin_airport` | Passed through |
| `destination_code` | `destination_airport` | Passed through |
| `barometric_altitude_ft` | `max_altitude_ft` | Cast to `int ≥ 0`; `null` on failure |
| `ground_speed_mph` | `avg_speed_mph` | Cast to `float ≥ 0`; `null` on failure |
| `playback_date` + `playback_time` + `playback_timezone` | `takeoff_time` | Combined as `YYYY-MM-DDTHH:MM:SS±HH:MM`; `null` if date is absent |
| _(hardcoded)_ | `num_screenshots` | Always `1` |

### Adapter-added provenance fields

Every intake record also carries:

| Field | Value |
|---|---|
| `confirmation_status` | `not_confirmed` |
| `intake_status` | `candidate_intake_ready` |
| `source_adapter` | `fr24_spiderweb_adapter_v0.1.0` |
| `source_candidate_id` | Original `candidate_id` |
| `source_image_path` | Original `image_path` |
| `source_image_name` | Original `image_name` |
| `review_status` | Preserved from export record |
| `selection_status` | Preserved from export record |
| `dedup_status` | Preserved from export record |
| `selected_field_disagreements` | Preserved |
| `missing_selected_fields` | Preserved |
| `conflict_count` | Preserved (int) |
| `export_version` | Preserved from export record |
| `fusion_version` | Preserved from export record |
| `field_select_version` | Preserved from export record |
| `dedup_version` | Preserved from export record |
| `parser_version` | Preserved from export record |

## Defense-in-depth label gate

The adapter enforces a two-stage prohibited-label check:

1. **Input gate**: if any value in the export record matches a prohibited label
   the record is silently dropped (counted in `prohibited_label_dropped`).
2. **Output gate**: after mapping, if the produced `flight_event` record
   somehow carries a prohibited label it is also dropped.

### Prohibited labels

- `confirmed`
- `confirmed_aircraft_event`
- `confirmed_anomaly`
- `confirmed_route`
- `verified_event`
- `validated_aircraft_event`

### Allowed status values

- `selected_candidate`
- `selected_with_review_required`
- `field_disagreement_review`
- `manual_review_required`
- `not_confirmed`
- `candidate_intake_ready`
- `selection_status_not_passthrough`
- `dashboard_review_accepted_after_manual_review`

## Summary JSON

```json
{
  "generated_at": "<ISO-8601>",
  "export_jsonl": "...",
  "output_jsonl": "...",
  "hold_jsonl": "...",
  "total_input_records": 120,
  "intake_records": 87,
  "hold_records": 33,
  "prohibited_label_dropped": 0,
  "validation_errors": [],
  "selection_status_counts": {"selected_candidate": 87, ...},
  "intake_status_counts": {"candidate_intake_ready": 87},
  "adapter_version": "fr24_spiderweb_adapter_v0.1.0",
  "policy": "candidate_only_no_auto_confirmation"
}
```

## Local validation

```bash
python -m py_compile fr24/spiderweb_adapter.py

python -m pytest tests/test_fr24_spiderweb_adapter.py -v

python fr24/spiderweb_adapter.py
```

## Next step

After validation, load `fr24_spiderweb_intake_candidates.jsonl` into the
Spiderweb operator dashboard so reviewers can triage and confirm flight events
by corridor.
