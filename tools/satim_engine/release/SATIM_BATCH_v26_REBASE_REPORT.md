# SATIM_BATCH_v26 Rebase Report

## Scope

Rebased graph ID patch onto current main after PR 36 reported not mergeable.

## Patch

- Graph builder now uses a source-local ordinal after resetting each source group index.
- Added a regression test proving unrelated rows do not change the target source graph edge target IDs.

## Status

Ready for CI verification.
