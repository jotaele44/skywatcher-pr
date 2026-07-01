# SATIM_BATCH_v24 Hotfix Report

## Scope

Patch the three P2 findings raised after PR #32 merge.

## Fixes

1. GPX parser dispatch
   - Added `parse_gpx_coordinates()` for `<trkpt>`, `<rtept>`, and `<wpt>` elements.
   - Added explicit `.csv` / `.kml` / `.gpx` dispatch in CLI.

2. Stable graph IDs
   - Replaced Python process-random `hash()` IDs with deterministic SHA-256 digest IDs.

3. Clean extraction directories
   - `extract_zips()` now removes the prior extraction directory before rebuilding a batch manifest.

## Tests

- GPX parsing test
- Stable graph ID test
- Extraction cleanup test
