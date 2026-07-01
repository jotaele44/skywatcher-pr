# SATIM_BATCH_v24 Hotfix Report

## Scope

Addresses three P2 review findings from PR #32 after merge.

## Fixes

1. GPX parser dispatch
   - Added `parse_gpx_coordinates()`.
   - Added `parse_track_file()` dispatch for CSV, KML, and GPX.
   - Updated CLI to use explicit dispatch instead of sending every non-CSV track to the KML parser.

2. Stable graph IDs
   - Replaced Python built-in `hash()` usage with deterministic SHA-256 based IDs.
   - Stabilizes graph node/edge IDs across interpreter processes and SATIM runs.

3. Clean extraction directories
   - `extract_zips()` now clears the full extraction root and per-zip target before extracting current inputs.
   - Prevents stale files from contaminating manifests when output directories are reused.

## Regression tests

Added tests for:

- GPX track parsing and dispatch.
- Stable graph IDs across repeated graph builds.
- Extraction cleanup removing stale files.

## Status

HOTFIX_READY_FOR_CI.
