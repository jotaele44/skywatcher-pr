# FR24 / RLSM guide (consolidated index)

The FlightRadar24 screenshot → RLSM (Restricted/Lossless Screenshot Mining)
pipeline is documented across several focused notes. Rather than merge them into
one file (and lose their git history), this guide is the **single entry point**
with a table of contents grouped by stage (T12-98).

## 1. Ingest & inventory
- [RUNBOOK_FR24_DATA_LOAD.md](RUNBOOK_FR24_DATA_LOAD.md) — load screenshots into the DB
- [FR24_MANIFEST_AUDIT.md](FR24_MANIFEST_AUDIT.md) — baseline manifest audit
- [FR24_DEDUP_FIELD_SELECTION.md](FR24_DEDUP_FIELD_SELECTION.md) — exact + perceptual dedup

## 2. OCR & extraction
- [FR24_OCR_ANALYSIS_VECTOR.md](FR24_OCR_ANALYSIS_VECTOR.md) — zone-based OCR analysis
- [FR24_SIDECAR_OCR_PIPELINE.md](FR24_SIDECAR_OCR_PIPELINE.md) — sidecar OCR pipeline
- [FR24_REGISTRATION_RECOVERY.md](FR24_REGISTRATION_RECOVERY.md) — tail-number recovery
- [FAA_REGISTRY_PIPELINE.md](FAA_REGISTRY_PIPELINE.md) — FAA N-number registry join

## 3. Region fusion & batch running
- [FR24_REGION_FUSION_BATCH_RUNNER.md](FR24_REGION_FUSION_BATCH_RUNNER.md)
- [FR24_ROI_BATCH_PLANNER.md](FR24_ROI_BATCH_PLANNER.md)

## 4. Candidate export & intake
- [FR24_SELECTED_CANDIDATES_EXPORT.md](FR24_SELECTED_CANDIDATES_EXPORT.md)
- [FR24_SPIDERWEB_INTAKE_ADAPTER.md](FR24_SPIDERWEB_INTAKE_ADAPTER.md)

## 5. Dashboard
- [FR24_DASHBOARD_UI.md](FR24_DASHBOARD_UI.md)

## Canonical model
- [RLSM_OPERATIONAL_ONTOLOGY_V0_1.md](RLSM_OPERATIONAL_ONTOLOGY_V0_1.md) — the
  canonical RLSM schema and vocabulary (`data/rlsm/schema.sql`).

### Operator outputs
- `outputs/rlsm_coverage_report.md` — coverage + per-zone/per-engine drift (T8-71)
- `outputs/ocr_failures.jsonl` — flat triage list of OCR failures (T8-70)
