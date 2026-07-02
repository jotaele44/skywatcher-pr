# SATIM route findings integration plan

## Objective

Connect the post-baseline ledgers to read-only route analysis while keeping the closed SATIM engine baseline unchanged.

## Inputs

- `SATIM_TRACK_LEDGER.csv`
- `SATIM_GRAPH_NODES.csv`
- `SATIM_GRAPH_EDGES.csv`
- `SATIM_GIS_JOIN_LEDGER.csv`
- `SATIM_ERROR_LEDGER.csv`
- `SATIM_MASTER_FILE_MANIFEST.csv`

## Later modules

| Module | Purpose |
|---|---|
| route_cluster_summary | summarize recurring route geometry |
| fn_candidate_builder | group flight-network candidates from track and graph ledgers |
| review_queue_builder | list rows that need manual review |
| rerun_report_renderer | render route reports from frozen ledgers |

## Guardrails

1. Do not alter SATIM engine production code in this wiring PR.
2. Do not commit bulky raw ZIPs or extracted outputs.
3. Use schemas and small fixtures before analysis automation.
4. Keep visual estimate tracks separate from timestamped coordinate tracks.
5. Tie findings to ledger provenance and confidence fields.

## Next implementation PR

Add schema validation, small fixtures, and a read-only route findings report generator.
