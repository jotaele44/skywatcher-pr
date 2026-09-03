# Skywatcher SATIM Media Decoder Build Report

Vector: `SKYWATCHER_SATIM_DEPENDENCY_AND_CI_PATCH`

Status: `CI_READY_PATCH_STAGED_STOP_BEFORE_MAIN_MERGE`

## Added / updated

| Component | Path | Purpose |
|---|---|---|
| Runtime media decoder | `scripts/satim_media_decoder.py` | Decode runtime media into sanitized frame manifests |
| Canonical artifact classifier | `scripts/classify_satim_artifacts.py` | Single conservative artifact-classifier CLI |
| Decoder tests | `tests/test_satim_media_decoder.py` | Validate extension support, source-reference hygiene, and dependency paths |
| Classifier tests | `tests/test_satim_artifact_classifier.py` | Validate `HOLD_REVIEW`, `TRACK_LINE`, and `TILE_SEAM` behavior |
| Dependencies | `requirements.txt` | Centralize runtime/test dependencies |
| CI workflow | `.github/workflows/satim-runtime-smoke-tests.yml` | Run synthetic-media smoke tests on PRs |

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
- CI tests use synthetic media only; no investigative media is required.

## Artifact-control rule

Unknown or weak rows default to `HOLD_REVIEW`, not `STRUCTURAL_SIGNAL`. `STRUCTURAL_SIGNAL` cannot be preserved by the classifier without downstream corroboration logic.

## Verification matrix

| Check | Status |
|---|---|
| Dependency declaration added | PASS |
| CI workflow added | PASS |
| Synthetic media tests added | PASS |
| Duplicate artifact classifier removed | PASS |
| Canonical classifier CLI retained | PASS |
| No source media committed | PASS |
| No source filename required in output | PASS |
| Main merge | STOPPED |

## Remaining work before production merge

| Gap | Severity | Notes |
|---|---:|---|
| Confirm CI pass on GitHub Actions | P1 | Workflow must run on PR after push. |
| Add richer synthetic PDF fixture | P2 | Current tests validate path/dependency behavior and source-hygiene controls. |
| Wire decoder output into SATIM visual ledger generation | P1 | Frame manifest is ready; visual row extraction remains downstream. |

## Stop condition

Stopped before main merge.
