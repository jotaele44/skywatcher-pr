# Skywatcher Floot donor reconciliation — 2026-09-12

## Status

PROVISIONAL / NONCANONICAL donor assessment. This file records bounded reconciliation decisions for the archived `Skywatcher PR.zip` snapshot (SHA-256 `9d272dc9decfd79a6198bfed9ef72fa5834914848e6d3033b0668e57c155e1a8`). It does not promote the archive over current `main` and does not assert that schema definitions contain historical database rows.

## Lens realignment

Current `main` already has a native iOS project under `ios/SkywatcherMobile`, a dedicated iOS GitHub Actions workflow, multiple SQLite-backed analytical subsystems, and producer-owned deterministic SQLite migration policy. Therefore the archived Floot/Vite application is a historical donor snapshot, not the target architecture.

## Archive surface

The donor contains 261 ZIP members. Relevant bounded persistence/runtime surfaces inspected in this reconciliation:

- `helpers/offlineStore.tsx`
- `helpers/offlineStoreIndexedDb.spec.tsx`
- `helpers/skywatcherWorkspace.tsx`
- `helpers/corpusIndex.tsx`
- `endpoints/health_GET.ts` + schema
- `endpoints/certification/status_GET.ts` + schema
- `package.json`

The donor's offline store uses IndexedDB database `skywatcher-pr-offline`, version 4, with stores for workspace state, corpus metadata, corpus chunks, corpus indexes, and corpus stable IDs. It explicitly checks raw/canonical cardinality, chunk/index continuity, manifest row counts, and stable-ID uniqueness before corpus activation.

## KEEP | REWRITE | LOCALIZE | SERVER_RETAIN | DROP

| Donor surface | Decision | Reason |
| --- | --- | --- |
| Raw/canonical row pairing invariants | KEEP | Preserves source representation separately from canonical observations and fails on cardinality mismatch. |
| Stable-ID uniqueness gate | KEEP | Hard identity invariant; should remain a pre-activation database constraint/test. |
| Generation manifest + row/chunk/index arithmetic | KEEP | Useful import/backup integrity model. |
| IndexedDB implementation | REWRITE | Browser-specific persistence must not become canonical iOS persistence. Preserve semantics, not implementation. |
| `LOCAL_STORAGE` / `MEMORY_ONLY` fallbacks | DROP as canonical storage | May remain UI/test fallbacks, but cannot certify durable corpus persistence. |
| Corpus/workspace storage on iOS | LOCALIZE | Bind to the existing native persistence/migration architecture; do not introduce a parallel database authority. |
| `health_GET` | SERVER_RETAIN only if an independent server remains | It has no reason to gate local iOS cold launch. |
| `certification/status_GET` source probe | REWRITE / SERVER_RETAIN | Remote GitHub head probing is network-dependent; local certification must use frozen build/input manifests, with remote status only supplemental. |
| Floot/Vite UI components | CANDIDATE donor only | Current fed UI/native surfaces outrank archive by default; migrate only demonstrated missing capability. |
| `postgres` package dependency | DROP from local iOS authority | Remote/shared services may retain PostgreSQL independently; device state remains local. |

## Database authority

Do **not** create a new federation-wide generic SQLite database merely because the donor used one browser database. Current Skywatcher already has producer-owned SQLite datasets with distinct authorities. The iOS layer should consume or create only bounded local stores whose ownership is explicit.

Proposed local mobile store responsibilities:

1. app/workspace state;
2. imported observation/corpus manifests;
3. locally generated screenshot-analysis records that are not already owned by another producer DB;
4. import receipts and migration receipts;
5. attachment references/hashes rather than unbounded opaque blobs where practical.

Existing analytical SQLite databases remain authoritative for their own bounded domains unless a separate migration proves equivalence.

## Donor-to-native invariant mapping

The native persistence pilot MUST reproduce these donor semantics before the browser store can be considered superseded:

- `raw_count == canonical_count` for every imported chunk/batch;
- stable observation IDs are non-null and unique inside the declared generation;
- declared row count equals persisted row count;
- index/manifest generation identifiers agree;
- incomplete generations never become active;
- previous active generation remains recoverable until replacement activation commits;
- backup/restore verifies checksums and schema version before replacing active state.

## Floot-unreachable acceptance gate

PASS requires an installed/native test target to:

1. cold-launch with Floot endpoints unavailable;
2. open existing local state;
3. import a bounded fixture;
4. reject duplicate stable IDs;
5. reject raw/canonical cardinality mismatch;
6. persist across termination/relaunch;
7. export a manifest-bound backup;
8. restore only after checksum + schema validation;
9. perform all of the above without remote GitHub/Floot success being required.

Until those tests pass, `FLOOT_INDEPENDENCE = PROVISIONAL`.

## What remains open

- exact mapping from the donor workspace/corpus types into the current native iOS model;
- whether any donor-only UI capability is absent from current fed surfaces;
- recovery of any historical browser IndexedDB contents, if such data still exists outside the ZIP;
- full byte-preserving archive import into Git history (the current connector write path can freeze text manifests but not bulk-import all archive members in one bounded operation);
- device/simulator persistence proof and backup/restore proof.
