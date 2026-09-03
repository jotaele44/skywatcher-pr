# Interactive Airspace Console Migration Ledger

## Policy

- SQLite migrations are producer-owned and do not mutate screenshot, export, or registry source artifacts.
- Every migration has a version, stable name, SHA-256 checksum, and UTC application timestamp.
- Rollback is supported.
- Rollback refuses to drop populated console tables unless `--allow-data-loss` is explicitly supplied.
- Migration statements run inside SQLite transactions.

## Ledger

| Version | Name | Direction | Objects | Data-loss posture | Status |
|---:|---|---|---|---|---|
| 1 | `phase1_console_contract_tables` | Up/down | `console_aircraft_states`, `console_track_points`, `console_flight_sessions`, `console_airport_operational_states`, indexes | Down blocked when populated unless explicitly overridden | Implemented |
| 2 | `phase2_repository_artifact_ledgers` | Up/down | `console_source_artifacts`, `console_repository_sync_runs`, indexes | V2 → V1 supported; down blocked when populated unless explicitly overridden | Implemented |

## Apply

```bash
python scripts/console_migrate.py path/to/flight_database.db
```

## Inspect

The command prints the applied migration ledger as JSON. The same ledger can be read through `server.backend.console.migrations.migration_ledger()`.

## Roll back an empty Phase 1 schema

```bash
python scripts/console_migrate.py path/to/flight_database.db --rollback --target 0
```

## Explicit destructive rollback

```bash
python scripts/console_migrate.py path/to/flight_database.db \
  --rollback --target 0 --allow-data-loss
```

Destructive rollback is never automatic.
