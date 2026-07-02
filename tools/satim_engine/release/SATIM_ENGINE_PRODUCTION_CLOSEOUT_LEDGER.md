# SATIM Engine Production Closeout Ledger

## Closeout status

| Item | Status |
|---|---|
| Stable baseline ref | Created |
| Release notes archive | Created |
| Merged commit ledger | Created |
| Stable vertex patch present on main | Confirmed |
| Final production status | Closed |

## Baseline reference

`baseline/stable-graph-id-baseline` points to:

`95ce71a56a2930dbd3f7d7fefd39246b591127e2`

## Merged commits

| PR | Purpose | Commit |
|---:|---|---|
| #32 | SATIM engine release candidate v0.21.0-rc1 | `4f23863c154ff43110d14912ba91c8f943f5b559` |
| #35 | GPX parser dispatch, stable ID first pass, extraction cleanup | `6dfbc03cb7918517b5dfbfacbe53cb111848bd02` |
| #38 | Source-local vertex ordinal graph ID stability patch | `95ce71a56a2930dbd3f7d7fefd39246b591127e2` |

## Production guardrails

1. Persisted graph IDs must be deterministic.
2. Do not use Python `hash()` for persisted identifiers.
3. Do not use global DataFrame row indexes for persisted identifiers.
4. Vertex IDs use source-local ordinals plus source, coordinate, and timestamp fields.
5. Batch composition changes must not alter IDs for unchanged source-local vertices.

## Closeout decision

SATIM Engine production closeout is complete at the stable graph ID baseline.
