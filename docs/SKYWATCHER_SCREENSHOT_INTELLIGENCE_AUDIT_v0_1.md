# Skywatcher Screenshot Intelligence Audit v0.1

## Scope

This pipeline converts each screenshot into reviewable observations while preserving the source image, SHA-256 identity, extraction method, confidence, and validation state. Pixel observations, GUI metadata, OCR output, associations, and geolocation inferences remain separate.

## Single command

```bash
./run-rlsm.sh --refresh-derived
./run-rlsm.sh --certify --gold-sample data/rlsm/gold_sample_300.jsonl
./run-rlsm.sh --status
```

`--certify` returns a non-zero exit code unless every required gate passes. A missing, malformed, unresolved, or non-300-record gold file is never treated as a passing label-recall result.

## Capability matrix

| Domain | Implementation | Certification evidence |
|---|---|---|
| Screenshot ingestion | Existing hash-addressed RLSM inventory | Disk-to-database accounting |
| OCR | Per-zone strict receipts; screenshot `ok`, `partial`, or `failed` | No missing receipts or errorless failures |
| Location and POI labels | Word-box and gazetteer extraction, including partial frames | Gold precision, recall, F1, and optional bbox IoU |
| Aircraft metadata | Registration, callsign, type, altitude, speed, heading, operator | Gold field accuracy and field provenance |
| Flight paths | Pixel-first route vectorization with explicit valid-negative and failure receipts | One receipt per ingested frame; zero hidden failures |
| Frame classification | Provider/layout evidence from OCR zones | One frame record per ingested screenshot |
| Map state | Viewport geometry only unless calibrated | Unsupported geolocation must retain null coordinates |
| GUI artifacts | Zone-level panel/control observations | Per-frame GUI observation coverage |
| Icons | Label-adjacent detection plus standalone tiled map/GUI scan | One scan receipt per frame; provisional candidates require review |
| Icon library | Deterministic PNG crops and source/crop hashes | Detected-to-captured accounting and zero capture failures |
| Satellite semantic features | Provider-neutral extraction contract exists; no benchmarked semantic detector is certified | Separate labeled satellite-imagery gold set and detector benchmark required |
| Cross-frame tracking | Not implemented in the current repair branch | Ordered screenshot sequences with independently reviewed identity links required |
| Provenance | Field-level source, method, confidence, and validation outcome | 100% coverage of non-null core fields |
| Structured exports | Deterministic JSONL files and SHA-256 manifest | Stable repeated export hashes |

## Required gates

1. `screenshot_accounting_100`
2. `no_silent_failures`
3. `frame_accounting_100`
4. `gui_artifact_frame_coverage_100`
5. `track_extraction_accounting_100`
6. `icon_scan_accounting_100`
7. `icon_capture_complete`
8. `no_unsupported_geolocation`
9. `field_level_provenance_100`
10. `location_label_recall_gte_0_98`

## Outputs

The pipeline writes:

- `outputs/screenshot_intelligence_audit.json`
- `outputs/screenshot_intelligence_audit.md`
- `outputs/screenshot_intelligence_capability_matrix.json`
- `outputs/screenshot_intelligence_errors.jsonl`
- `outputs/screenshot_intelligence_structured_sample.jsonl`
- `outputs/screenshot_intelligence/manifest.json`
- one deterministic JSONL export for each extended observation and receipt table
- `outputs/icon_library_manifest.jsonl`
- deterministic icon PNG crops beneath `outputs/icon_library/`

## Gold sample contract

The canonical operator file is `data/rlsm/gold_sample_300.jsonl`. Each line identifies a corpus screenshot by `screenshot_id`, SHA-256, or filename and may annotate labels, bounding boxes, frame type, aircraft fields, track shape, and icons. The schema is `schemas/rlsm/gold_sample.v1.schema.json`; `data/rlsm/gold_sample_300.example.jsonl` is illustrative only.

The 300 records must be stratified across provider/layout, portrait and landscape, map style, zoom, resolution, compression, selected and unselected aircraft, visible and absent paths, dense labels, occlusion, and low-quality frames. Annotation and review should be performed independently.

## Interpretation controls

- `GUI_LABEL`, `OCR_TEXT`, and `GUI_ICON` are direct interface observations.
- Pixel-detected paths and icons are observations with extraction confidence, not identity claims.
- Text-to-object linkage is an inferred association until validated.
- Geographic coordinates remain null when the screenshot lacks a supported calibration transform.
- Standalone icon candidates use provisional classes and `needs_review`; they are not promoted to confirmed POIs.
- Heuristic flight-path fallback is retained for information recovery but cannot satisfy a failed pixel-extraction receipt.
- Semantic interpretations of buildings, runways, roads, vessels, terrain, or other satellite-image content remain uncertified until a labeled imagery benchmark exists.
- Cross-frame identity continuity remains uncertified until ordered sequences and reviewed association truth are available.

## Current operational dependency

Repository CI can validate schemas, stage wiring, deterministic exports, and synthetic fixtures. Full certification requires the operator-local screenshot corpus and the independently reviewed 300-frame annotation file; neither should be committed if they contain private or licensed source imagery.
