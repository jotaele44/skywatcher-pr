# Phase 0 Review Remediation Ledger

## Target

- Pull request: `#110`
- Review vector: `REMEDIATE_SKYWATCHER_PHASE_0_REVIEW_FINDINGS_v2`
- Reconciled current-main parent: `71a4bbd42692a397eb3b76f37d9bd00c85ba7ef7`
- Certified remediation code head before documentation-only updates: `a8dbb794933900604156de05e8b426bdd0d5ffdd`
- PR disposition: draft, open, unmerged

## Scope preservation

- No remediation-authored changes under `frontend/`.
- Current-main frontend files were carried into the branch byte-for-byte through merge parents.
- No changes under `data/`.
- Public analytical schemas remain compatible.
- `operational_cueing=false` and intent/purpose inference remains prohibited.

## Findings and closure

| Review finding | Remediation | Closure gate |
|---|---|---|
| Branch was behind and non-mergeable | Added current `main` as true merge parents, preserved all current-main security and frontend commits | PR reports mergeable and zero commits behind |
| Installed CLI could validate zero schemas successfully | `validate` now fails when the repository schema directory is absent or empty; `--root` explicitly identifies repository assets | Isolated wheel test runs outside checkout, expects rootless validation failure, then validates 43+ schemas with explicit root |
| Wheel smoke only imported from checkout | Added clean virtual-environment wheel install from an empty directory | Backend-core Python 3.10–3.13 matrix |
| ZIP replacement could delete the old target before promotion | Default replacement is disabled; explicit replacement uses backup rename, promotion, and rollback | Core and standalone SATIM archive tests |
| ZIP limits trusted metadata only | Enforced streamed per-member and aggregate byte limits and final size equality | Adversarial archive tests |
| Windows path aliases were not blocked | Rejected alternate-data-stream colons, reserved device names, trailing dots/spaces, duplicates, traversal, symlinks, and encrypted entries | Adversarial archive tests |
| Core and SATIM archive implementations diverged | Both distributable implementations use the same contract and defaults | Nested-package parity test and SATIM CI |
| Diagnostic API accepted caller-owned IDs | IDs are server-generated, collision-checked, immutable, and reserved fields are rejected | API security tests |
| Review payloads were unbounded | Added 64 KiB and 128-field limits | API security tests |
| Known-aircraft lookup used substring matches | Added normalized exact identifiers and an explicit alias registry | FPIM regression tests |
| Legacy mission and operating-pattern claims lacked field provenance | Registry retains identifiers only; fields remain inactive until source URI, source record ID, capture time, and SHA-256 are present | FPIM exact-match/provenance tests |
| Active reports exposed mission and predictive operating patterns | Active profile always reports role as `Unknown (not inferred)` and exposes no typical hours or high-activity-region fields | FPIM regression tests |
| Source export removed executable modes | Export reads Git index modes and preserves executable launchers | Export-mode test and template drift |
| Hygiene scanner and export exclusions differed | Added one canonical repository policy for both operations | Repository-policy tests and backend-core hygiene gate |
| Dependency lock used editable sibling paths | Lock and fresh resolution require exact TheHub VCS commit references | CI lock job and pip-audit |
| Current-main security controls could be lost during reconciliation | Preserved CodeQL, secret scan, pip-audit, Dependabot, pre-commit, Ruff, mypy, coverage, pinned Actions, and frontend checks | Current-main plus Phase 0 workflow set |
| Coverage floor conflicted with data-independent core defaults | Backend-core remains data-independent; full CI explicitly runs the full-data suite for the preserved 55% floor | Both workflow families must pass |

## Security boundaries

Aircraft profile enrichment is field-provenance gated. Merely appearing in a legacy registry does not establish owner, operator, role, mission, schedule, destination, or typical operating area. Unknown or unproven fields remain `Unknown`.

Archive extraction is validation-first, stream-bounded, and recoverable. Existing destinations are refused by default. Explicit replacement retains a rollback path until promotion succeeds.

Diagnostic writes remain disabled by default and require both `PRII_ENABLE_WRITES=true` and a matching bearer token. Repository files are never mutated by the overlay.

## Certification record

The remediation code head completed all eleven triggered workflow families successfully:

- Backend core
- Skywatcher CI
- CodeQL
- Secret scan
- pip-audit
- Federation template drift
- desktop-build
- SATIM Engine CI
- SATIM Route Findings CI
- SATIM Runtime Smoke Tests
- SATIM Phase 2 Contracts

Documentation-only successor heads must rerun all workflows applicable to their changed paths before review closure is final.
