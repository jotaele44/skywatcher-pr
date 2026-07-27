# Phase 0 Test Evidence

## Original local certification

Environment: isolated Linux workspace, Python 3.13.5. The supplied audit archive intentionally omitted `frontend/` and production `data/`.

| Gate | Result |
|---|---|
| Core collection without production data or sibling checkout | PASS |
| Data-independent core suite | 754 passed, 36 skipped, 53 deselected |
| Minimum preserved core baseline | PASS — exceeds 738 |
| Original safe-archive and API-security focused suite | 12 passed |
| Federation exporter compatibility suite | 16 passed, 1 skipped (`requires_thehub`) |
| JSON Schemas | 43 compiled, 0 failures |
| Runtime `sys.path.insert` / `append` | 0 sites |
| Unsafe `ZipFile.extractall()` | 0 canonical sites |
| Nested tool suites | 60 passed (55 SATIM engine + 5 route findings) |
| PEP 517 editable install | PASS with local installed build toolchain and `--no-build-isolation` |
| Deterministic source export | PASS — two 648-file exports were byte-identical and excluded frontend/data/generated artifacts |

## Review-remediation certification

The reconciled remediation code head `a8dbb794933900604156de05e8b426bdd0d5ffdd` completed every triggered workflow family successfully.

| Gate | Result |
|---|---|
| Branch synchronization | PASS — current `main` is a merge parent and the PR is mergeable |
| Backend core Python matrix | PASS — Python 3.10, 3.11, 3.12, and 3.13 |
| Repository hygiene | PASS — canonical generated-artifact rules |
| JSON Schema validation | PASS — explicit-root validation checks a nonzero set of at least 43 schemas |
| Rootless installed CLI behavior | PASS — `skywatcher validate` fails outside a repository when schemas are absent |
| True isolated wheel install | PASS — clean virtual environment, empty working directory, explicit repository root |
| Deterministic source export | PASS — duplicate archives compare byte-for-byte and preserve executable modes |
| Full-data test and coverage matrix | PASS — Python 3.10, 3.11, and 3.12 with the 55% floor retained |
| Data-independent core gate | PASS — production data and TheHub checkout are not required |
| Immutable dependency resolution | PASS — exact TheHub SHA in committed and freshly resolved locks; no editable sibling paths |
| API authentication and identity tests | PASS — disabled-by-default writes, bearer token, server-owned immutable IDs, reserved-field rejection, payload limits |
| Archive adversarial tests | PASS — traversal, Windows aliases, symlink, duplicate, ratio, streamed limits, no-replace default, replacement promotion |
| FPIM policy tests | PASS — exact identifier matching, unverified fields remain inactive, role unresolved, no operating-pattern cueing |
| SATIM Engine CI | PASS |
| SATIM Route Findings CI | PASS |
| SATIM Runtime Smoke Tests | PASS |
| SATIM Phase 2 Contracts | PASS |
| Federation template drift | PASS |
| Desktop packaging | PASS — Ubuntu, macOS, and Windows |
| Frontend regression build | PASS — preserved current-main frontend lint and build |
| CodeQL | PASS |
| Secret scan | PASS |
| pip-audit | PASS |
| Ruff and mypy visibility | PASS — report-only jobs completed without masking other gates |

## Coverage-tier reconciliation

A diagnostic run proved the data-independent suite itself was healthy: 729 tests passed, but 52 data-capability tests were intentionally deselected, producing 51.98% coverage against the preserved 55% full-repository floor. The correction was not to lower the floor. Instead:

- `Backend core` continues to certify a clean, data-independent install.
- `Skywatcher CI` explicitly runs the full-data test tier for coverage.

This preserves both reproducibility and the current-main coverage ratchet.

## Evidence policy

Any code change after the recorded code head invalidates its workflow evidence. Documentation-only successor heads must rerun all workflows applicable to their paths; the final pull-request body records the latest head and conclusions.
