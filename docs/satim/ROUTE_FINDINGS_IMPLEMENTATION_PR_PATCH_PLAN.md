# SATIM route findings implementation PR patch plan

## Branch

`feature/satim-route-findings-readonly`

## Scope

Build a read-only route findings module that consumes SATIM CSV ledgers from a user-provided artifact directory and writes derived summary outputs to a separate output directory.

## Added implementation files

| Path | Purpose |
|---|---|
| `tools/satim_route_findings/pyproject.toml` | package metadata and CLI entry point |
| `tools/satim_route_findings/satim_route_findings/loaders.py` | read-only CSV ledger loaders |
| `tools/satim_route_findings/satim_route_findings/schemas.py` | required-column schema validation |
| `tools/satim_route_findings/satim_route_findings/cluster_summary.py` | recurring route bucket summary |
| `tools/satim_route_findings/satim_route_findings/fn_candidates.py` | route-network candidate summary from graph ledgers |
| `tools/satim_route_findings/satim_route_findings/review_queue.py` | manual review queue output |
| `tools/satim_route_findings/satim_route_findings/report.py` | CSV and Markdown report writer |
| `tools/satim_route_findings/satim_route_findings/cli.py` | command-line entry point |

## Added tests and fixtures

| Path | Purpose |
|---|---|
| `tools/satim_route_findings/tests/fixtures/*.csv` | small synthetic fixture ledgers only |
| `tools/satim_route_findings/tests/test_route_findings.py` | schema, output, guardrail, deterministic order, and CLI tests |
| `.github/workflows/satim-route-findings-ci.yml` | route-findings CI path filter |

## Output files produced by the module

- `route_cluster_summary.csv`
- `fn_candidate_summary.csv`
- `review_queue.csv`
- `route_findings_report.md`

## Guardrails preserved

- No changes to `tools/satim_engine/`
- No raw source ZIP commits
- No full SATIM ledger commits
- Inputs remain read-only
- Outputs are blocked from being written into the input tree
- Output order is deterministic under tests

## Recommended next step

Open a PR from `feature/satim-route-findings-readonly` into `main`, wait for CI, then review final diff before merge.
