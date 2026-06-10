# FR24 Region OCR Fusion and Batch Runner

## Purpose

This pipeline extends the FR24 sidecar + OCR pipeline (see
[FR24_SIDECAR_OCR_PIPELINE.md](FR24_SIDECAR_OCR_PIPELINE.md)) with:

1. **Region-level OCR parsing** — extracts candidate fields from per-region
   OCR crops (callsign, altitude, speed, route, panel).
2. **OCR fusion** — merges whole-image and region-level parsed candidates
   side-by-side; detects field-level conflicts; routes conflicts to review.
3. **Full-corpus batch runner** — resumable OCR runner over the full batch
   plan; logs all completions and failures; never crashes on a bad image.
4. **Batch status reporter** — reads the ledger and reports completion counts.
5. **Review queue builder** — prioritizes fused candidates that need manual
   inspection.

All outputs are candidates. No confirmed labels are emitted.

---

## Strict operating rules

| Rule | Description |
|---|---|
| No source mutation | Source screenshots are never modified. |
| No raw file deletion | Raw files are never deleted or moved. |
| No confirmed labels | `review_status` never equals `confirmed`, `confirmed_anomaly`, `confirmed_aircraft_event`, or `confirmed_infrastructure`. |
| Conflict → review | Any field-level disagreement between whole-image and region OCR is routed to `fusion_conflict_review`, not silently merged. |
| Provenance preserved | Every output row retains `image_path`, `sidecar_path`, `match_band`, `resolved_status`, `parser_version`, `ocr_region`. |

---

## Inputs

| File | Produced by |
|---|---|
| `fr24_manifest_with_sidecars.csv` | `fr24/sidecar_reconcile.py` |
| `fr24_ocr_probe_50.jsonl` | `fr24/ocr_probe.py` |
| `fr24_region_ocr_results.jsonl` | `fr24/batch_run.py --mode region` |
| `fr24_full_corpus_batch_plan.csv` | `fr24/batch_plan.py` (or hand-built) |

---

## Commands

### 1. Parse region OCR results

```bash
python fr24/region_parse.py \
  --input-jsonl data/_manifests/fr24_audit/fr24_region_ocr_results.jsonl \
  --output-csv  data/_manifests/fr24_audit/fr24_region_parsed_events.csv
```

Outputs:

| File | Purpose |
|---|---|
| `fr24_region_parsed_events.csv` | Structured candidate fields per region-crop |

Parser extracts candidate values based on `region_type`:

| region_type | Fields extracted |
|---|---|
| `callsign` | callsign_or_label |
| `altitude` | barometric_altitude_ft |
| `speed` | ground_speed_mph |
| `route` | origin_code, destination_code |
| `panel`, `unknown` | all fields |

### 2. Parse whole-image OCR (if not already done)

```bash
python fr24/ocr_parse.py \
  --input-jsonl data/_manifests/fr24_audit/fr24_ocr_probe_50.jsonl \
  --output-csv  data/_manifests/fr24_audit/fr24_ocr_parsed_events_probe_50.csv \
  --review-csv  data/_manifests/fr24_audit/fr24_ocr_review_queue_probe_50.csv
```

### 3. Fuse whole-image and region candidates

```bash
python fr24/ocr_fusion.py \
  --whole-image-csv data/_manifests/fr24_audit/fr24_ocr_parsed_events_probe_50.csv \
  --region-csv      data/_manifests/fr24_audit/fr24_region_parsed_events.csv \
  --output-csv      data/_manifests/fr24_audit/fr24_fused_event_candidates.csv \
  --review-csv      data/_manifests/fr24_audit/fr24_fused_review_queue.csv
```

**Conflict detection:** for each key field (`callsign_or_label`, `registration`,
`aircraft_type`, `barometric_altitude_ft`, `ground_speed_mph`, `origin_code`,
`destination_code`) — if both whole-image and region supply a non-empty,
non-matching value, the field is added to `conflict_fields` and
`review_status` is set to `fusion_conflict_review`.

Output columns include side-by-side pairs: `callsign_or_label_wi` /
`callsign_or_label_region`, etc.

### 4. Run a batch (whole-image mode)

```bash
python fr24/batch_run.py \
  --batch-plan data/_manifests/fr24_audit/fr24_full_corpus_batch_plan.csv \
  --batch-id   fr24_batch_0001 \
  --mode       whole-image \
  --limit      25
```

### 5. Run a batch (region mode)

```bash
python fr24/batch_run.py \
  --batch-plan data/_manifests/fr24_audit/fr24_full_corpus_batch_plan.csv \
  --batch-id   fr24_batch_0001 \
  --mode       region
```

Region mode uses `fr24_ui_segmenter.FR24UISegmenter` to crop panel,
callsign, altitude, speed, and route regions before running OCR.

**Resumability:** re-running the same `--batch-id` + `--mode` skips images
already recorded as `status=complete` in the ledger.

Outputs:

| File | Purpose |
|---|---|
| `batches/fr24_batch_0001_ocr.jsonl` | Whole-image OCR records |
| `batches/fr24_batch_0001_region_ocr.jsonl` | Region OCR records |
| `batches/fr24_batch_0001_status.json` | Batch completion summary |
| `fr24_batch_run_ledger.csv` | Append-mode run ledger |
| `fr24_batch_error_queue.csv` | Failed-image error queue |

### 6. Check batch status

```bash
python fr24/batch_status.py \
  --ledger data/_manifests/fr24_audit/fr24_batch_run_ledger.csv
```

Returns JSON with per-batch-id, per-mode completion counts.

### 7. Build prioritized review queue

```bash
python fr24/review_queue_builder.py \
  --fused-csv  data/_manifests/fr24_audit/fr24_fused_event_candidates.csv \
  --review-csv data/_manifests/fr24_audit/fr24_fused_review_queue.csv
```

---

## Output files reference

| File | Produced by | Description |
|---|---|---|
| `fr24_region_parsed_events.csv` | `fr24/region_parse.py` | Candidate fields per region |
| `fr24_fused_event_candidates.csv` | `fr24/ocr_fusion.py` | Fused candidates with side-by-side fields |
| `fr24_fused_review_queue.csv` | `fr24/ocr_fusion.py` / `fr24/review_queue_builder.py` | Conflict and review records |
| `fr24_batch_run_ledger.csv` | `fr24/batch_run.py` | Append-mode completion ledger |
| `fr24_batch_error_queue.csv` | `fr24/batch_run.py` | Failed image error queue |
| `batches/fr24_batch_0001_ocr.jsonl` | `fr24/batch_run.py` | Whole-image OCR JSONL |
| `batches/fr24_batch_0001_region_ocr.jsonl` | `fr24/batch_run.py` | Region OCR JSONL |
| `batches/fr24_batch_0001_status.json` | `fr24/batch_run.py` | Batch run summary |

---

## Review status vocabulary

| Value | Meaning |
|---|---|
| `fused_candidate` | Whole-image and region agree; ready for downstream pipeline |
| `fusion_conflict_review` | At least one key field conflicts between sources |
| `fusion_no_region_match` | No region OCR row for this image |
| `fusion_region_only` | Region OCR exists but no whole-image OCR row |
| `region_parsed_candidate` | Region OCR parsed successfully |
| `region_low_text_review` | Region OCR returned < 20 chars |
| `region_ocr_failed` | Region OCR failed with error |
| `region_manual_review_required` | Region parsed but confidence too low |

Disallowed labels (never emitted): `confirmed`, `confirmed_anomaly`,
`confirmed_aircraft_event`, `confirmed_infrastructure`.

---

## JSON schema

See [schemas/fr24_event_candidate_schema.json](../schemas/fr24_event_candidate_schema.json)
for the full field reference and allowed enum values.

---

## Conservative interpretation policy

All parsed outputs are candidates. OCR text is noisy and may misread
callsigns, registration numbers, aircraft types, route fields, or map labels.
Do not treat any OCR-derived field as a confirmed fact without independent
validation.

---

## Next vector

After full-corpus batch runs stabilize, move to:
- Cross-batch deduplication
- Confidence-weighted field selection for fused candidates
- Human-in-the-loop review workflow for `fusion_conflict_review` rows
