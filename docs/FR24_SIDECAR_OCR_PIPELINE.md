# FR24 Sidecar + OCR Pipeline

## Purpose

This pipeline extends the FR24 manifest audit gate with three read-only stages:

1. Reconcile timestamp-renamed screenshots to Google Takeout supplemental metadata JSON.
2. Select and OCR a small strong-match probe set.
3. Parse OCR text into structured candidate flight/event fields.

The tools do not mutate source screenshots or sidecar JSON files.

## Local corpus state used for validation

The local corpus audit passed after quarantining two truncated PNG files:

- Total valid images: 7,687
- Corrupt: 0
- Duplicates: 0
- Git-tracked raw files: none
- Google Takeout sidecars detected: 6,900

The filename lineage mismatch is expected: screenshots were timestamp-renamed while Google Takeout sidecars retain original names such as `IMG_6047.PNG.supplemental-metadata.json`.

## Commands

### 1. Reconcile sidecars

```bash
python fr24/sidecar_reconcile.py \
  --root "data/Flight Logs" \
  --output-dir data/_manifests/fr24_audit
```

Outputs:

| File | Purpose |
|---|---|
| `fr24_sidecar_reconciliation_candidates.csv` | nearest timestamp candidates |
| `fr24_sidecar_reconciliation_summary.json` | candidate match summary |
| `fr24_sidecar_reconciliation_resolved.csv` | one-to-one resolved matches |
| `fr24_manifest_with_sidecars.csv` | OCR-safe manifest |
| `fr24_sidecar_review_queue.csv` | weak/conflict/unmatched review queue |
| `fr24_sidecar_reconciliation_resolved_summary.json` | final linkage summary |

Expected local validation result:

| Field | Count |
|---|---:|
| Primary sidecar matches | 6,098 |
| Strong matches | 6,083 |
| Metadata gaps | 836 |
| Sidecar duplicate conflicts | 753 |

### 2. Run OCR probe

```bash
python fr24/ocr_probe.py \
  --manifest data/_manifests/fr24_audit/fr24_manifest_with_sidecars.csv \
  --output-dir data/_manifests/fr24_audit \
  --limit 50
```

Outputs:

| File | Purpose |
|---|---|
| `fr24_ocr_probe_50.csv` | selected probe manifest |
| `fr24_ocr_probe_50.jsonl` | OCR text records |
| `fr24_ocr_probe_50_results.csv` | OCR status table |
| `fr24_ocr_probe_50_summary.json` | OCR probe summary |

Observed local validation result:

| Field | Count |
|---|---:|
| Probe images | 50 |
| OCR complete | 50 |
| OCR failed | 0 |
| Low-text images | 1 |

### 3. Parse OCR output

```bash
python fr24/ocr_parse.py \
  --input-jsonl data/_manifests/fr24_audit/fr24_ocr_probe_50.jsonl \
  --output-csv data/_manifests/fr24_audit/fr24_ocr_parsed_events_probe_50.csv \
  --review-csv data/_manifests/fr24_audit/fr24_ocr_review_queue_probe_50.csv
```

Outputs:

| File | Purpose |
|---|---|
| `fr24_ocr_parsed_events_probe_50.csv` | structured candidate event fields |
| `fr24_ocr_review_queue_probe_50.csv` | records requiring manual review |

Observed parser yield:

| Field | Count |
|---|---:|
| Records | 50 |
| Parsed candidates | 28 |
| Manual review | 21 |
| Low-text review | 1 |
| Aircraft type parsed | 38 |
| Registration parsed | 38 |
| Speed parsed | 38 |
| Altitude parsed | 29 |

## Conservative interpretation policy

All parsed outputs are candidates. OCR text is noisy and may misread callsigns, registration numbers, aircraft types, route fields, or map labels.

Do not treat OCR-derived fields as confirmed facts without independent validation.

Allowed labels:

- `parsed_candidate`
- `manual_review_required`
- `low_text_review`
- `sidecar_linked`
- `weak_sidecar_match_review`
- `sidecar_conflict_review`
- `metadata_gap`

Disallowed automatic labels:

- `confirmed`
- `confirmed_anomaly`
- `confirmed_aircraft_event`
- `confirmed_infrastructure`

## Next vector

After the probe parser stabilizes, move to ROI-aware OCR and full-corpus batch planning.
