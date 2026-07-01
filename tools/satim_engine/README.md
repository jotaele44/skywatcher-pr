# SATIM Engine v21

Deployable SATIM batch engine package.

## Install

```bash
python -m pip install -e .[dev]
```

## Run

```bash
satim --input /path/to/zips --output outputs/satim_run
```

## Outputs

- `SATIM_MASTER_FILE_MANIFEST.csv`
- `SATIM_TRACK_LEDGER.csv`
- `SATIM_GRAPH_NODES.csv`
- `SATIM_GRAPH_EDGES.csv`
- `SATIM_ERROR_LEDGER.csv`
- `SATIM_RUN_REPORT.md`

## Provenance rule

Only timestamped track exports can produce verified geometry. Screenshot-only geometry remains approximate.
