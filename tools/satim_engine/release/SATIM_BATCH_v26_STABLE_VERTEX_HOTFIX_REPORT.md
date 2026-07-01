# SATIM_BATCH_v26 Stable Vertex Hotfix Report

## Scope

Patch the remaining P2 finding from PR #35: vertex IDs must not depend on global DataFrame indexes assigned by batch concatenation.

## Fix

- `build_graph_from_ledgers()` now resets the index inside each source group and uses a per-source ordinal in the vertex digest.
- Source grouping is sorted for deterministic traversal.

## Regression coverage

- Added a test proving that inserting an unrelated source file before the target source does not change the target source vertex ID.
