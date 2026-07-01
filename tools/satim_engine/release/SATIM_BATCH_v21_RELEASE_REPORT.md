# SATIM_BATCH_v21 Release Candidate Report

## Scope

Clean non-blocking warnings, add CI workflow, add version tag, add changelog, and package SATIM as a release candidate.

## Release candidate

- Package: `satim-engine`
- Version: `0.21.0-rc1`
- Base: SATIM_BATCH_v19 production engine
- Operational validation source: SATIM_BATCH_v20 final run

## Warning cleanup

The pandas concat FutureWarning from v20 was addressed by filtering empty/all-NA track frames before concatenation. This does not change track scoring semantics.

## CI

Added `.github/workflows/satim-engine-ci.yml` with:

- Python 3.11 setup
- editable install with dev extras
- pytest
- CLI smoke test against a zipped sample track

## Status

RELEASE_CANDIDATE_READY.
