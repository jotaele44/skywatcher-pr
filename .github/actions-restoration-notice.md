# GitHub Actions Restoration Notice

**Date:** 2026-09-19  
**Status:** RESTORED

## Summary

GitHub Actions runners were unavailable from approximately 2026-09-06 through
2026-09-19. Workflows triggered during that window completed as `failure`
immediately with `runner_id: 0`, `steps: []`, and no usable logs.

## Exit criteria

Close this notice once at least one representative workflow on the current
`main` head allocates a real runner (`runner_id != 0`), executes its steps,
and publishes usable logs.
