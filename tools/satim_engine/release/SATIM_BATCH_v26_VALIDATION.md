# SATIM_BATCH_v26 Validation

## Target defect

Global DataFrame indexes could enter vertex IDs and cause ID changes when unrelated tracks are inserted before a source in the batch.

## Validation coverage

- Per-source ordinal regression test
- Batch-composition change regression test
- Stable ID helper test
- Source-row ordering determinism test

## Expected result

The same source-local vertices retain the same IDs even when unrelated track files are added to the batch.
