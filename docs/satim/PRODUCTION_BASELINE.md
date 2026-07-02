# SATIM production baseline

## Baseline lock

- Baseline ref: `baseline/stable-graph-id-baseline`
- Baseline commit: `95ce71a56a2930dbd3f7d7fefd39246b591127e2`
- Engine status: closed
- Repo patch posture: hold unless a new defect is confirmed

## Merged sequence

| PR | Purpose | Main commit | Status |
|---:|---|---|---|
| #32 | SATIM engine release candidate | `4f23863c154ff43110d14912ba91c8f943f5b559` | merged |
| #35 | GPX parser dispatch, stable ID first pass, extraction cleanup | `6dfbc03cb7918517b5dfbfacbe53cb111848bd02` | merged |
| #38 | Source-local vertex ordinal graph ID stability | `95ce71a56a2930dbd3f7d7fefd39246b591127e2` | merged |

## Stable graph ID rule

Persisted SATIM graph IDs must be deterministic. They must not use Python `hash()` or batch-global DataFrame indexes. Vertex IDs use source-local ordinals with source, coordinate, and timestamp fields.

## Wiring rule

This document wires the closed SATIM production baseline into the repo without committing bulky raw source ZIPs or full rerun outputs.
