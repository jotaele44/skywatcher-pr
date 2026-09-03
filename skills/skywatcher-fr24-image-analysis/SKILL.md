# Skywatcher FR24 Image Analysis

## Purpose

Execute a deterministic two-stage workflow for new FR24 screenshots, image sets, image PDFs, or videos:

1. **Stage 1 — flight evidence extraction**: preserve sources, inventory frames, segment UI, extract displayed flight fields, fuse same-flight frames, vectorize the route, georegister only when calibration evidence is adequate, and freeze the result.
2. **Stage 2 — SATIM imagery analysis**: derive basemap-only frames, mask FR24 UI/labels/route overlays, compare repeat views, classify seams/render artifacts/shadows/radiometric boundaries/persistent surface observations, and freeze the result.
3. **Correlation** occurs only after both stages are frozen and may report proximity, overlap, uncertainty, and temporal status. It must not infer mission, intent, target, facility purpose, or causality.

## Invocation

Use when a user supplies a new image, image collection, image PDF, or video and asks to analyze FR24 flight data, basemap imagery, seams, artifacts, or both.

Recommended command:

```bash
python -m fr24_image_skill run INPUT --output-dir OUTPUT --mode standard
```

Modes:

- `triage`: inventory, hashes, lightweight extraction, obvious artifact flags.
- `standard`: complete two-stage internal workflow.
- `forensic`: standard workflow plus strict provenance, external-evidence registration inputs, contradiction accounting, and package validation.

## Required invariants

- Account for 100% of source files and derived frames.
- Hash every original and derived artifact.
- Keep device capture time separate from FR24 replay time.
- Preserve raw pixel-space track geometry before any geographic transformation.
- Never promote fixed Puerto Rico bounds to a located observation.
- Freeze Stage 1 before Stage 2.
- Mask route/UI/labels before terrain or imagery classification.
- Every finding is either classified or explicitly unresolved.
- Do not infer facility purpose from imagery alone.
- Do not infer flight mission, target, surveillance, or intent from route geometry or proximity.
- Runs are resumable and deterministic for the same inputs/configuration.

## Inputs

Required: one or more images, an image PDF, or a video.

Optional:

- FR24 CSV/export
- manual flight log
- KML/GeoJSON
- independent satellite/aerial imagery
- DEM
- orthophoto
- known control points

## Outputs

- `RUN_MANIFEST.json`
- `SOURCE_INVENTORY.csv`
- `SOURCE_CHECKSUMS.sha256`
- `STAGE_1_FLIGHT_OBSERVATION.json`
- `STAGE_1_OCR_LEDGER.csv`
- `STAGE_1_TRACK_RAW.geojson`
- `STAGE_1_TRACK_REGISTERED.geojson`
- `STAGE_1_CALIBRATION_LEDGER.csv`
- `STAGE_2_SATIM_FINDINGS.geojson`
- `STAGE_2_ARTIFACT_LEDGER.csv`
- `STAGE_2_REPEAT_VIEW_MATRIX.csv`
- `CORRELATION_LEDGER.csv`
- `CONTRADICTION_LEDGER.csv`
- `MANUAL_REVIEW_QUEUE.csv`
- `VALIDATION_REPORT.md`

## Evidence language

Allowed: “The reconstructed route passes within the reported uncertainty corridor of the imagery finding.”

Forbidden: “The aircraft inspected, surveyed, or targeted the site.”

## Existing repository modules

The orchestrator should adapt existing Skywatcher components where available, including screenshot inventory, UI segmentation, OCR, sidecar reconciliation, flight fusion, route vectorization, affine georegistration, SATIM engines/classifiers, and review queues. Missing optional dependencies must produce an explicit degraded-state record rather than fabricated output.
