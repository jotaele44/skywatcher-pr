# Phase 0 Test Evidence

## Original Phase 0 baselines

| Gate | Result |
|---|---|
| Data-independent core suite | 754 passed, 36 skipped, 53 capability tests deselected |
| Minimum preserved core baseline | PASS — exceeds 738 |
| JSON Schemas | 43 compiled, 0 failures |
| Runtime `sys.path.insert` / `append` | 0 active sites at original certification |
| Unsafe `ZipFile.extractall()` | 0 canonical sites |
| Nested tool suites | 60 passed at original certification |
| Deterministic source export | Two 648-file exports were byte-identical |

## Country-provenance remediation code head

Certified code head: `a773a378abdbc536f1334e757fd0cfcf077594c7`

Current-main merge parent: `e7eab8b496a0dfc40fa4de34f02a18466ea75a0d`

| Gate | Result |
|---|---|
| Branch synchronization | PASS — current `main` is a true merge parent; `behind_by=0` |
| Pull-request state | PASS — open, draft, mergeable, unmerged |
| Scope preservation | PASS — no remediation-authored frontend or production-data differences |
| Backend core matrix | PASS — Python 3.10, 3.11, 3.12, and 3.13 |
| Rootless installed CLI | PASS — validation fails when repository schemas are absent |
| Explicit-root schema validation | PASS — nonzero repository schema set validated |
| Isolated wheel install | PASS on every backend-core Python version |
| Repository hygiene | PASS |
| Deterministic source export | PASS, including executable-mode preservation |
| Full-data coverage matrix | PASS — Python 3.10, 3.11, and 3.12 with the 55% floor retained |
| Frontend regression | PASS — `npm ci`, lint, and production build |
| Immutable dependency resolution | PASS — exact TheHub SHA, no sibling editables, committed lock equals fresh resolver output |
| API authentication and identity | PASS — disabled-by-default writes, token enforcement, server-owned immutable IDs, payload bounds |
| Field-level provenance | PASS — incomplete provenance remains inactive; complete provenance activates only the supported fields |
| Country provenance | PASS — unknown `N...` and `YN...` identifiers remain `Unknown`; incomplete provenance remains inactive; complete provenance activates only country |
| Callsign-prefix isolation | PASS — active identity lookup does not consult compatibility prefix tables |
| Flight-history isolation | PASS — populated database rows cannot promote aircraft type, owner, operator, or country |
| No-intent report boundary | PASS — role unresolved, no mission list, no operating-hours/high-activity cueing, no unproven identity output |
| Active-report country boundary | PASS — report emits `Country: Unknown` unless complete field provenance activates country |
| Archive adversarial contract | PASS — traversal, aliases, symlink, duplicate, ratio, streamed limits, and no-replace default |
| Archive rollback failure path | PASS — original restored and temp/backup state cleaned after injected promotion failure |
| Standalone archive parity | PASS — distributable SATIM package carries the same rollback regression |
| Import-form CodeQL regressions | PASS — desktop and both archive-test mixed-import alerts auto-resolved |
| CodeQL | PASS — Python and JavaScript/TypeScript |
| Secret scan | PASS |
| pip-audit | PASS |
| Federation template drift | PASS |
| Desktop packaging | PASS — Ubuntu, macOS, and Windows frozen-app smoke/package matrix |
| SATIM Engine CI | PASS |
| SATIM Route Findings CI | PASS |
| SATIM Runtime Smoke Tests | PASS |
| SATIM Phase 2 Contracts | PASS |

## Workflow evidence for certified code head

| Workflow family | Run | Conclusion |
|---|---:|---|
| Backend core | `30313038722` | success |
| Skywatcher CI | `30313038703` | success |
| CodeQL | `30313038802` | success |
| Secret scan | `30313038705` | success |
| pip-audit | `30313038692` | success |
| Federation template drift | `30313038687` | success |
| desktop-build | `30313038704` | success |
| SATIM Engine CI | `30313038688` | success |
| SATIM Route Findings CI | `30313038699` | success |
| SATIM Runtime Smoke Tests | `30313038693` | success |
| SATIM Phase 2 Contracts | `30313038691` | success |

## Country-provenance regression coverage

- Unknown `N...` identifier leaves country `Unknown`.
- Unknown `YN...` identifier leaves country `Unknown`.
- Incomplete country provenance leaves country inactive.
- Complete country provenance activates only country and no unsupported identity field.
- Active report output remains `Country: Unknown` without complete field provenance.

## Lock regeneration evidence

The first synchronized run intentionally failed the new drift check after successfully creating and uploading the authoritative resolver output. Artifact `8669841881`, named `resolved-lock-be98653a17955a11ad1a8be193a1d438b6124e29`, had digest `sha256:e68f8ce33b79626fbeca41efc9dcc9ef34e6315e0896fb34f921210f2ff35c17`.

The artifact was committed unchanged as `requirements.lock`. On the certified code head, the fresh normalized resolver output matched the committed lock byte-for-byte and the lock job concluded successfully.

## Evidence policy

Any code change after the certified code head invalidates this code certification. Documentation-only successor heads must rerun workflows applicable to their changed paths. The pull-request body records the final evidence head and final conclusions.
