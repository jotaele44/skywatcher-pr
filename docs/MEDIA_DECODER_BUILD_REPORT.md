# Skywatcher SATIM Media Decoder Build Report

Vector: `SKYWATCHER_SATIM_MEDIA_DECODER_BUILD`

Status: `PATCH_STAGED_STOP_BEFORE_MAIN_MERGE`

## Added

| Component | Path | Purpose |
|---|---|---|
| Runtime media decoder | `scripts/satim_media_decoder.py` | Decode runtime media into sanitized frame manifests |
| Decoder tests | `tests/test_satim_media_decoder.py` | Validate extension support, source-reference hygiene, and dependency paths |

## Supported runtime input types

- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`
- `.heic`
- `.heif`
- `.webp`
- `.tif`
- `.tiff`

## Decoder behavior

| Input | Decoder path | Output |
|---|---|---|
| PDF | PyMuPDF / `fitz` | One frame-manifest row per page |
| JPG/JPEG/PNG/WEBP/TIF/TIFF | Pillow | One frame-manifest row per image |
| HEIC/HEIF | `pillow-heif` + Pillow | One frame-manifest row per image |

## Source-protection controls

- Source media are never copied into the repo.
- Runtime input path is not emitted into frame manifest output.
- Source filename is not used as fallback `run_id`.
- Output uses `source_reference=runtime_input_not_committed`.
- Tests assert that private source filename text does not appear in decoded output.

## Hold-review / artifact-control linkage

This decoder only produces frame manifests. Artifact classification remains downstream and must retain the existing conservative rule: unknown rows default to `HOLD_REVIEW`, not `STRUCTURAL_SIGNAL`.

## Merge blockers remaining

| Gap | Severity | Notes |
|---|---:|---|
| Dependency declaration not centralized | P1 | Add `requirements.txt` or `pyproject.toml` with Pillow, PyMuPDF, pytest, and optional pillow-heif. |
| Duplicate artifact classifier scripts remain | P1 | Consolidate into one canonical CLI. |
| Full CI not wired | P1 | Add CI job once project-wide test conventions are established. |

## Stop condition

Stopped before main merge.
