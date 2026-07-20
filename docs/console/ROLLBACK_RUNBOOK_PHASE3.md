# Phase 3 Rollback Runbook

## Immediate runtime disable

Build with:

```bash
VITE_SKYWATCHER_CONSOLE_ENABLED=false npm run build
```

Result:

- `/console` displays a controlled disabled state.
- MapLibre is not initialized.
- No console API bootstrap is attempted by the page component.
- Existing diagnostic routes remain operational.

## Branch rollback

Phase 3 is isolated on `agent/skywatcher-console-phase3` and proposed through a stacked draft PR based on `agent/skywatcher-console-phase2`. Closing the draft PR or resetting the Phase 3 branch does not alter Phase 1 or Phase 2.

## Dependency rollback

Remove the exact `maplibre-gl` dependency and Phase 3 frontend files, restore the prior route/layout/provider files, and regenerate `package-lock.json`. No SQLite rollback is required because Phase 3 adds no database migration.

## Operational trigger conditions

Disable or roll back Phase 3 when any of the following is observed:

- Map create/remove or observer create/disconnect imbalance.
- External requests in blank mode.
- Provider credential or proprietary asset detection.
- Serious or critical accessibility regression.
- Native desktop WebGL initialization failure on a supported target.
- Unrecoverable route regression in existing diagnostic pages.
