# Route findings analysis PR blueprint

## Branch

`docs/route-findings-analysis-pr-plan`

## Objective

Design a read-only route findings lane that consumes frozen SATIM post-baseline ledgers without changing SATIM engine production code or committing raw source payloads.

## Inputs

| Input ledger | Purpose |
|---|---|
| `SATIM_TRACK_LEDGER.csv` | source-local coordinate rows and verification fields |
| `SATIM_GRAPH_NODES.csv` | deterministic track and vertex nodes |
| `SATIM_GRAPH_EDGES.csv` | track-to-vertex graph links |
| `SATIM_GIS_JOIN_LEDGER.csv` | spatial context joins for route rows |
| `SATIM_ERROR_LEDGER.csv` | parser and processing error review source |

## Proposed read-only module

`tools/satim_route_findings/`

| File | Purpose |
|---|---|
| `__init__.py` | package marker |
| `schemas.py` | validates required columns and schema expectations |
| `loaders.py` | loads CSV ledgers from a user-provided artifact path |
| `cluster_summary.py` | summarizes recurring route geometry by source and spatial buckets |
| `fn_candidates.py` | builds candidate flight-network groups from graph and track ledgers |
| `review_queue.py` | emits manual-review queues for missing fields, low confidence, or sparse geometry |
| `report.py` | renders Markdown and CSV report outputs |
| `cli.py` | read-only CLI entry point |

## Output artifacts

| Output | Format | Content |
|---|---|---|
| `route_cluster_summary.csv` | CSV | recurring source and spatial-bucket summaries |
| `fn_candidate_summary.csv` | CSV | candidate FN groups and confidence fields |
| `review_queue.csv` | CSV | rows requiring manual review |
| `route_findings_report.md` | Markdown | plain-language summary tied to provenance |

## Small fixtures

Use tiny synthetic fixtures only:

| Fixture | Rows | Purpose |
|---|---:|---|
| `track_ledger_min.csv` | 6-12 | cluster summary smoke test |
| `graph_nodes_min.csv` | 4-8 | graph ID join smoke test |
| `graph_edges_min.csv` | 3-6 | track-to-vertex edge smoke test |
| `gis_join_min.csv` | 6-12 | spatial context smoke test |
| `error_ledger_empty.csv` | 0-1 | empty-error path test |

## Test matrix

| Test | Assertion |
|---|---|
| schema validation | required columns are enforced |
| read-only loader | no writes occur outside output directory |
| route cluster summary | deterministic output order |
| FN candidate summary | candidate groups are reproducible |
| review queue | low-confidence and missing-field rows are flagged |
| no engine import mutation | SATIM engine package is not modified |

## Guardrails

1. Do not change `tools/satim_engine/src` in this PR.
2. Do not commit raw ZIPs or full extracted ledgers.
3. Use only small synthetic fixtures.
4. Keep outputs provenance-bound.
5. Treat visual-estimate rows separately from timestamped coordinate rows.
6. Make the module read-only against inputs.

## PR scope

This should be a new implementation PR after this blueprint is reviewed. It should add route-findings tooling, fixtures, and tests, but it should not alter the closed SATIM engine baseline.
