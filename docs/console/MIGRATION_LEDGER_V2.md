# Interactive Airspace Console Migration Ledger v2

## Policy

- Migrations are additive and transactional.
- Source artifacts remain read-only and are never rewritten by migration code.
- Every migration records a stable version, name, SHA-256 checksum, and UTC application time.
- Rollback from V2 to V1 is supported.
- Populated V2 tables cannot be dropped without explicit `--allow-data-loss` authorization.

## Ledger

| Version | Name | SHA-256 checksum | Objects | Rollback posture | Status |
|---:|---|---|---|---|---|
| 1 | `phase1_console_contract_tables` | `6970511222e262e39b3177d3a9d433e162b3244e1a722e0056f42b330b0fa01e` | Normalized aircraft states, track points, flight sessions, airport states | Blocked when populated unless explicitly authorized | implemented |
| 2 | `phase2_repository_artifact_ledgers` | `27676b3b7d26137b17e2dd6a467b39eb2dd5a9fdb6859998abe8b8b5b46b49d4` | `console_source_artifacts`, `console_repository_sync_runs`, indexes | V2 → V1 supported; blocked when populated unless explicitly authorized | implemented |

## V2 purpose

Migration V2 records artifact-level provenance and repository synchronization receipts without changing or copying source files.

```text
console_source_artifacts
console_repository_sync_runs
```

## Apply through V2

```bash
python scripts/console_migrate.py path/to/flight_database.db --target 2
```

## Roll back to V1

```bash
python scripts/console_migrate.py path/to/flight_database.db --rollback --target 1
```

## Explicit destructive rollback

```bash
python scripts/console_migrate.py path/to/flight_database.db \
  --rollback --target 1 --allow-data-loss
```

Destructive rollback is never automatic.
