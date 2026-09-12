# Floot archive database-authority matrix

Status: PROVISIONAL / NONCANONICAL donor reconciliation

Frozen donor ZIP: `Skywatcher PR.zip`
SHA-256: `9d272dc9decfd79a6198bfed9ef72fa5834914848e6d3033b0668e57c155e1a8`
Members: 261

## Binding rules

1. Current fed implementation outranks the Floot donor unless harder evidence reverses the binding.
2. Schema definitions do not establish historical database contents.
3. SQLite engine identity does not imply database-authority identity.
4. Existing producer/domain databases must not be cloned into a mobile-local authority without an explicit authority migration.
5. RAW, NORMALIZED, and CANONICAL representations remain distinct.
6. Mobile state may reference producer records by durable IDs/manifests; it must not silently fork producer truth.

## Current authority inventory

| Surface | Current role | Authority state | Mobile treatment |
| --- | --- | --- | --- |
| `src/skywatcher/fr24/database.py` + `database_migrations.py` | FR24/airspace relational persistence and migration ledger | PRODUCER AUTHORITY | REFERENCE / DO NOT CLONE |
| RLSM SQLite family under `fr24/` and `data/rlsm/` | screenshot-derived observations, route/features, labels, calibration/provenance | PRODUCER/ANALYTICAL AUTHORITY | REFERENCE / IMPORT RECEIPTS ONLY |
| Console SQLite migrations (`scripts/console_migrate.py`, migration ledger) | console-local producer-owned state | PRODUCER-OWNED | REFERENCE |
| FPIM aircraft profile SQLite access | aircraft-profile/domain reads | DOMAIN AUTHORITY | REFERENCE |
| Native iOS `ios/SkywatcherMobile` | screenshot analyzer/UI/share-extension surface | MOBILE CLIENT | MAY OWN MOBILE-LOCAL STATE ONLY |
| Floot IndexedDB donor (`workspace`, corpus stores/indexes/IDs) | historical browser-local state | NONCANONICAL DONOR | LOCALIZE SEMANTICS, REWRITE STORAGE |
| Floot `health_GET` / certification status handlers | historical server/runtime status | NONCANONICAL DONOR | SERVER_RETAIN or REWRITE; never mobile truth |

## Proposed set relation

### INTERSECTION

Semantics already represented in the fed repo or compatible with its existing architecture:

- offline/local analytical operation;
- deterministic migration/version concepts;
- provenance and source-manifest discipline;
- stable identifiers for persisted analytical records;
- fail-closed validation before promotion;
- SQLite-backed durable producer state;
- native iOS execution target.

### ARCHIVE_ONLY

Bounded donor residue not currently established as native-mobile persistence:

- browser workspace state;
- corpus generation manifests;
- chunk/index generation activation semantics;
- local corpus import receipts;
- donor backup/restore semantics for browser-local workspaces;
- exact Floot GUI manifestations not already represented by native/web fed surfaces.

These are CANDIDATE capabilities, not identities with current records.

### FED_ONLY

Current capabilities that materially supersede the archive:

- native Swift/iOS project and Xcode CI workflow;
- FR24 producer SQLite migrations;
- RLSM analytical SQLite corpus and derived pipelines;
- federation contracts and authority boundaries;
- current GIS/track/terrain capabilities;
- current tests, migration ledgers, and domain-specific backend services.

### SYMMETRIC_DIFFERENCE

`ARCHIVE_ONLY ∪ FED_ONLY` above. No equivalence claim is made solely from names or similar function labels.

## KEEP | REWRITE | LOCALIZE | SERVER_RETAIN | DROP

| Donor component/semantic | Disposition | Reason |
| --- | --- | --- |
| RAW→CANONICAL row-count closure | KEEP | migration invariant |
| stable-ID uniqueness | KEEP | identity/integrity invariant |
| generation manifest arithmetic | KEEP | prevents partial corpus activation |
| activate only after complete verification | KEEP | fail-closed invariant |
| IndexedDB as canonical persistence | REWRITE | native target requires durable mobile storage; browser authority not retained |
| workspace state | LOCALIZE | legitimate device-local authority |
| import manifests/receipts | LOCALIZE | legitimate device-local authority |
| backup/restore metadata | LOCALIZE | legitimate device-local authority |
| producer aircraft/flight/route tables | DROP AS MOBILE DUPLICATES | already owned by current producer databases |
| memory fallback as authoritative state | DROP | silent-loss risk |
| server health/status endpoints | SERVER_RETAIN / REWRITE | network/runtime concern, not mobile canonical state |
| Floot service bindings | DROP/REWRITE | no Floot runtime dependency permitted for certified native path |

## Bounded mobile-local schema

The mobile client may introduce a dedicated local database only for residue that is not already producer-owned. Candidate tables:

- `schema_migrations`
- `workspace_state`
- `import_manifest`
- `import_receipt`
- `local_annotation`
- `attachment_manifest`
- `backup_receipt`
- `sync_state`

Producer/domain rows should be referenced using durable producer IDs plus source/database manifestation metadata. A mobile-local table named like an existing producer table is prohibited unless an explicit authority migration is separately reviewed and certified.

## Required invariants

Before an imported generation becomes active:

- source row count == retained + excluded + unresolved;
- RAW count and canonical-count relationship is explicitly declared and closes arithmetically;
- required stable IDs are unique within their declared authority scope;
- no unexplained duplicate IDs;
- every manifest-declared member/chunk exists and hashes as declared;
- index generation and data generation identifiers match;
- incomplete or failed generation remains inactive;
- prior active generation remains usable after failed import/migration;
- backup manifest hashes verify before restore replaces active state;
- restore record counts and required IDs match the backup receipt.

## iOS acceptance gates

PASS requires all of the following on the native project:

1. cold launch with Floot unreachable;
2. create/update mobile-local workspace state;
3. force termination and relaunch with exact persistence;
4. import a positive fixture and verify counts/IDs;
5. reject duplicate-ID and incomplete-generation negative fixtures without activating them;
6. export a hash-bound backup;
7. mutate local state, restore the backup, and verify counts + hashes;
8. verify no producer database is silently duplicated as a new mobile authority;
9. unsigned iOS simulator/device build-test-analyze/archive workflow passes.

Until those gates pass, `FLOOT_INDEPENDENT_IOS` remains OPEN.
