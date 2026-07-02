# SATIM Engine Production Release Notes

## Baseline

- Baseline ref: `baseline/stable-graph-id-baseline`
- Baseline commit: `95ce71a56a2930dbd3f7d7fefd39246b591127e2`
- Repository: `jotaele44/skywatcher-pr`

## Production sequence

| Stage | PR | Main commit | Result |
|---|---:|---|---|
| SATIM v21 release candidate | #32 | `4f23863c154ff43110d14912ba91c8f943f5b559` | Merged |
| SATIM v24 parser/ID/extraction hotfix | #35 | `6dfbc03cb7918517b5dfbfacbe53cb111848bd02` | Merged |
| SATIM v26 stable vertex ID patch | #38 | `95ce71a56a2930dbd3f7d7fefd39246b591127e2` | Merged |

## Final stable-ID rule

SATIM persisted graph IDs must not use Python `hash()` or batch-global DataFrame row indexes. The production baseline uses deterministic SHA-256 digests and source-local point ordinals.

## Confirmed production surface

- `tools/satim_engine/src/satim_engine/graph.py`
- `tools/satim_engine/src/satim_engine/tracks.py`
- `tools/satim_engine/src/satim_engine/inventory.py`
- `tools/satim_engine/src/satim_engine/cli.py`
- SATIM parser, graph, and regression test suite

## Status

Production baseline archived.
