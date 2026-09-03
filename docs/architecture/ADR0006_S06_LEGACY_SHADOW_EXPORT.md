# ADR 0006 S06 — legacy shadow export and dual-run lane projection foundation

S06 adds the offline Skywatcher-owned evidence preparation boundary needed before
ADR 0006 dual-run execution. It does not execute the legacy path, invoke a model
or provider, read credentials, access RLSM or any other database, launch a worker,
or mutate production state.

## Frozen contract

`schemas/ai_imagery/legacy_shadow_export.v1.schema.json` defines a
content-addressed, non-production legacy shadow export. The exact schema SHA-256
is recorded in `schemas/ai_imagery/FROZEN.sha256`.

A valid export binds:

- TheHub H08 campaign and trial identity;
- exact Skywatcher revision, source-set digest and pin-set digest;
- the actual legacy extraction engine and revision;
- a full signed execution receipt by run ID and receipt SHA-256;
- the exact campaign source artifacts and complete terminal dispositions;
- exact deterministic output IDs and normalized SHA-256 values;
- complete field-level provider, model, prompt, policy, source and extraction
  provenance;
- normalized legacy CSV, checkpoint and log records without relabeling;
- historical CSV/checkpoint/log artifact digests using relative paths only; and
- permanently false production mutation, certification, active-promotion and
  retirement-authorization flags.

Historical CSV rows without complete model-run and field provenance cannot form a
valid export. S06 never invents provider, model, prompt, policy, access-context,
source or review metadata.

## H08 lane projection

`src/skywatcher/ai_imagery/dual_run_projection.py` provides pure builders for:

- a `LEGACY_SHADOW` H08 lane record from a valid legacy export; and
- an `ADR0006_CANDIDATE` H08 lane record from the deterministic S05 package.

The candidate projection recomputes the S05 normalized package digest and all
eight package-file digests:

- `manifest.json`
- `source_artifacts.json`
- `aviation_extractions.json`
- `model_field_provenance.json`
- `provisional_signals.json`
- `processing_receipts.json`
- `exclusions.json`
- `failures.json`

The campaign must require exactly that output set. Source count, terminal input
accounting, required-output count and actual produced-output count are bound to
the campaign and package contents. Candidate projection requires both H06 job and
H07 admission references.

S06 consumes only a compact execution-receipt reference already marked verified
by an upstream verifier. It does not verify Ed25519 itself. TheHub H09 remains
responsible for resolving the full generic receipt, recomputing its payload and
object digests, verifying the signature through a trusted-key resolver and then
supplying the verified compact reference.

## Deterministic staging layout

`write_dual_run_evidence_staging()` writes one trial into a deterministic,
relative-path-only package rooted at a caller-supplied empty directory. It writes
campaign, policy, full execution receipts, legacy export, both H08 lane records,
the complete S05 package and a sorted `SHA256SUMS` file.

No absolute workstation paths, traversal segments, secret-shaped keys or
secret-shaped values are serializable. Repeating the write with identical inputs
produces byte-identical package files and identical digests.

## Cross-repository compatibility

The test fixtures contain exact byte snapshots of TheHub H08 campaign and lane
schemas from TheHub `main@d4b849c0e6d4ab01584c0f4eed32267a3663ca99`:

- campaign schema SHA-256
  `f97918e9742b0d815824c93817350c4bcdc5d6e68e14e749b60e24542c899e64`;
- lane schema SHA-256
  `d9b75bfc2a9867da088d10ffb3e4538313f88417c65661de9f3813d1525a919b`.

Generated legacy and candidate lane records validate against that exact H08 lane
schema.

## Preserved boundaries

The existing `scripts/fr24_vision_ingest.py` remains deprecated and unchanged.
S06 does not execute it. S06 does not read or write RLSM, call Anthropic or another
provider, load credentials, launch subprocesses or containers, acquire artifacts,
certify evidence, promote snapshots, retrieve evidence, answer queries, delete
legacy state or authorize retirement.
