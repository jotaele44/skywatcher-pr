# Skywatcher SATIM Runtime Input Smoke Test Ledger

Vector: `SKYWATCHER_SATIM_ENGINE_SMOKE_TEST`

Status: `PASS_WITH_ENGINE_GAP`

## Scope

Smoke-test the runtime intake contract and artifact-classifier defaults without committing or referencing source screenshots, PDFs, images, phone exports, or investigation-specific ledgers.

## Runtime media policy

- Source media are runtime-only.
- Source media are not committed.
- Source media filenames are not recorded in committed ledgers.
- Output rows must use `source_packet=runtime_input_not_committed` or equivalent sanitized language.

## Intake smoke test

| Runtime input type | Manifest accepted | Output source reference sanitized | Result |
|---|---:|---:|---|
| PDF | yes | yes | PASS |
| JPG | yes | yes | PASS |
| JPEG | yes | yes | PASS |
| HEIC | yes | yes | PASS |

## Output-reference verification

| Check | Result |
|---|---|
| No committed source media file required | PASS |
| No committed source filename required | PASS |
| Output event row uses sanitized source packet value | PASS |
| Runtime path excluded from output row | PASS |
| Default evidence tier remains conservative | PASS |

## Artifact-classifier smoke test

| Input description | Expected class | Observed class | Result |
|---|---|---|---|
| `unclassified visual texture` | `HOLD_REVIEW` | `HOLD_REVIEW` | PASS |
| `FR24 playback diagonal track line` | `TRACK_LINE` | `TRACK_LINE` | PASS |
| `rectilinear tile seam and mixed epoch boundary` | `TILE_SEAM` | `TILE_SEAM` | PASS |

## Merge blockers / engine gaps

| Gap | Severity | Notes |
|---|---:|---|
| Media decoding is not yet implemented | P0 | Current smoke test validates manifest intake and sanitized ledger output, not extraction of frames/pages from each media type. |
| HEIC decoding dependency is not specified | P0 | Add explicit dependency or fallback converter before production use. |
| PDF page extraction is not yet wired to visual ledger generation | P0 | Needed before real SATIM page/frame rows can be automated. |
| Duplicate classifier scripts remain | P1 | Consolidate `classify_satim_artifacts.py` and `satim_artifact_classifier.py` into one canonical CLI. |
| No CI smoke test exists | P1 | Add a test using synthetic local fixtures only; no investigative media. |

## Validation result

`PASS_WITH_ENGINE_GAP`: runtime-input contract and non-reference policy pass. Full engine readiness remains blocked until actual media decoding/frame extraction is implemented.

## Stop condition

Stopped before main merge.
