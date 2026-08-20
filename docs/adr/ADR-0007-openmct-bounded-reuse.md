# ADR-0007: Bounded Open MCT reuse

Status: Proposed
Baseline: `e171e81fb1ef8419386aa2b7e85c9a0e546c5ec8`

## Decision

Skywatcher may embed a pinned Open MCT v4.1.0 distribution only as a read-only replay and visualization surface. Skywatcher remains authoritative for source artifacts, canonical observations, UTC normalization, uncertainty, confidence, provenance, source accounting, review state, exports, and replay receipts.

Open MCT MUST NOT write canonical records, derive authoritative identities or tracks, fetch runtime assets from the network, control live sensors, or become required for existing RLSM workflows.

## Dependency boundary

- Version: `v4.1.0`
- License: Apache-2.0; preserve upstream license and notices.
- Packaging: local vendored release artifact with SHA-256 and SBOM.
- Runtime egress: prohibited.
- Upgrade: explicit reviewed PR only.

The release binary is intentionally not committed by this foundation change until its upstream artifact, exact digest, license set, Node requirement, browser matrix, and build provenance are certified. `vendor/openmct/v4.1.0/RELEASE.json` is the fail-closed admission record.

## Invariants

1. Replay access is read-only.
2. Every displayed datum resolves to a canonical record or an explicitly labelled synthetic fixture.
3. Raw, corrected, observed, receipt, ingestion, and display times remain distinguishable.
4. Unknown time uncertainty is never represented as zero.
5. Missing source accounting blocks certification.
6. Interpolated values are distinct from observations.
7. Disabling the feature removes the replay route without a database rollback.
8. Existing RLSM tests and workflows remain unchanged.

## Foundation scope

This PR adds versioned JSON schemas, stable object identifiers, bounded query validation, deterministic replay receipts, a read-only SQLite opener, a disabled-by-default feature flag, one synthetic fixture, and tests. It does not add sensor adapters or promote an Open MCT bundle.

## Acceptance gates

- exact dependency admission receipt
- no runtime egress
- read-only database enforcement
- stable object IDs
- JSON schema validation
- deterministic receipt hashing
- feature-flag rollback
- canonical database hash unchanged
- existing RLSM tests green

## Rollback

Set `SKYWATCHER_OPENMCT_REPLAY_ENABLED=false` or remove replay route registration. No canonical schema migration is required.
