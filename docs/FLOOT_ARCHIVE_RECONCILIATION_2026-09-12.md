# Floot archive reconciliation — 2026-09-12

## Frozen input

- Archive: `Skywatcher PR.zip`
- SHA-256: `9d272dc9decfd79a6198bfed9ef72fa5834914848e6d3033b0668e57c155e1a8`
- ZIP members: 253
- Uncompressed bytes: 692254
- ZIP CRC validation: PASS
- Archive status: historical source manifestation; not canonical over current `main`.

## Current-repo authority

The current fed repo already has a producer-owned SQLite migration framework with versioned, checksummed migrations, UTC application timestamps, transaction boundaries, rollback support, and explicit data-loss refusal. That framework remains authoritative. No second SQLite migration authority should be introduced.

## Floot storage plane observed

The archived GUI contains an IndexedDB workspace/corpus implementation named `skywatcher-pr-offline`, DB version 4, with stores for workspace state, corpus metadata, corpus chunks, corpus indexes, and corpus stable IDs. It enforces generation continuity, raw/canonical row-cardinality equality, stable-ID uniqueness, index counts, chunk counts, and row-count closure before corpus activation.

The archived Hono server exposes only `_api/health` and `_api/certification/status` plus static serving. The observation corpus is therefore not dependent on the archived server data plane.

## Reconciliation classification

| Archive component | Decision | Rationale |
|---|---|---|
| Offline corpus identity/invariant logic | KEEP | Strong integrity gates; preserve behavior and tests. |
| IndexedDB persistence implementation | LOCALIZE | Keep for web compatibility; map durable iOS authority to the repo's SQLite discipline. |
| LocalStorage fallback | KEEP_BOUNDED | Compatibility only; never canonical corpus authority. |
| Memory-only fallback | KEEP_BOUNDED | Test/runtime fallback only; never persistence authority. |
| `_api/health` | DROP_OR_REPLACE | Floot-era server health endpoint is not required for offline app authority. |
| `_api/certification/status` | SERVER_RETAIN_OPTIONAL | Keep only if certification requires a remote/shared authority; offline operation must not depend on it. |
| Static Hono serving | DROP_FOR_IOS | Capacitor/native packaging supplies bundled application assets. |
| Corpus import/backup/restore semantics | KEEP | Required for portability and recovery. |
| Existing fed-repo SQLite migration ledger | KEEP_CANONICAL | Current hard evidence outranks the earlier proposal for a new shared package. |

## Migration rule

Do not migrate Floot IndexedDB records by schema inference alone. A migration may consume only an explicit exported workspace/corpus backup or another frozen recoverable data artifact. Schema definitions prove structure, not record existence.

The iOS storage adapter must preserve the archived invariants:

1. generation identity;
2. stable-ID uniqueness;
3. raw/canonical one-row-to-one-row cardinality;
4. chunk/index continuity;
5. row-count closure;
6. atomic activation only after verification;
7. rollback/restore without silent data loss.

## Authority model

- Source artifacts: immutable evidence inputs.
- Current fed-repo SQLite migrations: canonical durable local migration authority.
- Web IndexedDB: compatibility/local web persistence.
- iOS SQLite: durable device persistence, implemented through the existing repo migration discipline.
- Remote services: optional/shared functions only; never silently override local records.

## Acceptance gates

- `main` remains unchanged until PR review.
- Existing SQLite migrations continue to pass.
- IndexedDB regression tests remain green for web builds.
- Explicit import from a frozen Floot workspace preserves counts and stable IDs.
- Cold launch with Floot unreachable succeeds.
- Airplane-mode corpus read/search/backup/restore succeeds.
- Local/remote authority conflicts fail closed.
- Backup manifest records schema version, app version, record counts, artifact hashes, and UTC export time.

## Certification state

- Archive preservation metadata: PASS
- Archive source imported into Git history: OPEN (branch created; full ZIP/source payload not yet committed)
- Storage reconciliation: PASS at architecture level
- Record migration: OPEN pending an actual frozen workspace/database export
- iOS SQLite adapter: OPEN
- Floot-unreachable device regression: OPEN
