# Interactive Airspace Console — Phase 2 Implementation

## Scope

Phase 2 connects the diagnostic API to bounded local artifacts and resolves declared-but-empty entity loaders. It does not introduce external network collection, the interactive map runtime, or production federation UI behavior.

## Repository adapters

- FR24 capture inventory.
- Manual review queue.
- Aircraft profiles.
- Track points.
- Route segments.
- Flight sessions.
- Aircraft states.
- Airport operational states.

Each adapter returns a repository snapshot containing rows, artifact receipts, availability status, explicit reason, warnings, skipped-row count, synthetic status, source dimensions, and provenance completeness.

## Artifact discovery

Discovery is bounded to documented repository paths and explicit environment overrides. The adapters do not search home directories, mounted volumes, browser data, or remote services.

## Empty-loader resolution

The generic `/api/entities/*` response body remains list-shaped for compatibility. Every entity response now includes:

```text
X-Skywatcher-Availability
X-Skywatcher-Availability-Reason
X-Skywatcher-Record-Count
X-Skywatcher-Provenance-Complete
```

A dedicated endpoint exposes the same status without relying on headers:

```http
GET /api/entities/{entity_name}/availability
```

## Console query services

Cursor-paginated diagnostic endpoints are added for repositories, captures, review items, profiles, aircraft states, flight sessions, tracks, routes, and airport operational states.

## Provenance and time policy

- Repository rows require complete row-level provenance.
- Artifact path and ingest adapter are recorded for every normalized repository row.
- Time-bearing rows must normalize to UTC.
- Timezone-naive legacy route points are skipped rather than assigned an invented timezone.
- Screenshot-derived routes remain evidence-only.
- Synthetic fixture rows remain explicitly synthetic and production-ineligible.

## Legacy bridge

When normalized V1 tables exist but contain no rows, repositories fall back to populated legacy `flights`, `track_points`, `screenshots`, and `aircraft_profiles` tables. Populated normalized tables always take precedence.

## Migration V2

Adds artifact and synchronization ledgers while preserving source artifacts:

```text
console_source_artifacts
console_repository_sync_runs
```

## Local validation

```text
python -m compileall -q server scripts tests
PASS

python -m pytest -q
27 passed
```

## Baseline artifact status

The repository currently commits two synthetic observation rows. Other Phase 2 adapters are implemented but report explicit `unavailable_no_artifact` until local or committed artifacts are supplied.
