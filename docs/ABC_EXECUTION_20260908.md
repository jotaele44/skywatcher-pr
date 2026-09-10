# A → C → B execution record — 2026-09-08

Full program: **OPEN**. Hosted runner admission: **BLOCKED**. This records bounded work, not universal completion.

## A: promotion and queue reconciliation

The tested repair at `7c60d0a0ccd681d9da3c60441a1cf9d576d6d03f` was pushed and opened as draft PR #270. Current main remains `39e1fb297e24cd9017167a8725b40e73dd0349e4`. The original 23 open PRs are retained; adding this repair makes 24. None were merged, closed, or declared equivalent. All original PR file lists and patches were captured with API pagination. File-set intersections are routing evidence, not merge-conflict or supersession proof.

All 24 failed check runs on the repair head report that the account billing lock prevented job startup; the dependent GUI E2E check was skipped. Do not rerun these until runner admission changes.

| PR | Review lane | Changed files | Files overlapping repair | Disposition |
|---|---|---:|---:|---|
| #269 | ASSESSMENT | 1 | 0 | OPEN / review required |
| #268 | SHARED_CONTRACT | 1 | 0 | OPEN / review required |
| #267 | DEPENDENCY_MIGRATION | 2 | 0 | OPEN / review required |
| #266 | DEPENDENCY_MIGRATION | 3 | 0 | OPEN / review required |
| #265 | DEPENDENCY_MIGRATION | 3 | 0 | OPEN / review required |
| #264 | DEPENDENCY_MIGRATION | 1 | 0 | OPEN / review required |
| #263 | DEPENDENCY_MIGRATION | 2 | 2 | OPEN / review required |
| #262 | DEPENDENCY_MIGRATION | 2 | 2 | OPEN / review required |
| #261 | DEPENDENCY_MIGRATION | 2 | 2 | OPEN / review required |
| #260 | DEPENDENCY_MIGRATION | 2 | 2 | OPEN / review required |
| #259 | DEPENDENCY_MIGRATION | 2 | 2 | OPEN / review required |
| #258 | DEPENDENCY_MIGRATION | 1 | 1 | OPEN / review required |
| #257 | DEPENDENCY_MIGRATION | 1 | 1 | OPEN / review required |
| #256 | DEPENDENCY_MIGRATION | 1 | 1 | OPEN / review required |
| #255 | DEPENDENCY_MIGRATION | 1 | 1 | OPEN / review required |
| #254 | DEPENDENCY_MIGRATION | 1 | 1 | OPEN / review required |
| #253 | SHARED_CONTRACT | 5 | 0 | OPEN / review required |
| #252 | SHARED_CONTRACT | 3 | 0 | OPEN / review required |
| #251 | SHARED_CONTRACT | 2 | 0 | OPEN / review required |
| #250 | PRODUCT_IMPLEMENTATION | 3 | 0 | OPEN / review required |
| #249 | PRODUCT_IMPLEMENTATION | 17 | 6 | OPEN / review required |
| #247 | SHARED_CONTRACT | 5 | 0 | OPEN / review required |
| #246 | SHARED_CONTRACT | 6 | 0 | OPEN / review required |

PR #251 pins its audit to the old main. Its exact-source workflow checks the diff against watched source paths, so it would fail after this repair. Re-audit the changed paths and bind new evidence before updating that contract. PR #249 overlaps the capability manifest, API startup/configuration and dependency files; validate the combined implementation. Major dependency proposals need their own migration tests. No absence of a file overlap is treated as merge readiness.

## C: completion inventory

All 1,885 original legacy findings are retained with unique IDs, an OPEN state, discovery classification, and no identity effect. The inventory excludes zero and adjudicates zero as resolved. The summary is in `COMPLETION_INVENTORY_20260908.json`; the complete row ledger is in the local evidence directory.

| Review group | Findings | Next evidence required |
|---|---:|---|
| FR24 evidence pipeline | 692 | Exact input receipts, row conservation, identity adjudication, API-to-visible-GUI tests |
| Operator/developer commands | 566 | Per-command decision: normal operator workflow or justified internal infrastructure |
| Analytical modules | 448 | Trace modules to actual workflows, expose results/provenance/recovery, validate identity boundaries |
| Console API | 140 | Trace endpoint calls through client state and visible workflows; verify errors and write guards |
| Authentication/navigation | 39 | Auth provider readiness, conditional route tests, link/control behavior and recovery |

The inventory includes 53 endpoint/UI signals (14 endpoints, 29 controls, four pages, five routes, one unreachable route). Prioritize these for direct runtime adjudication; the broader module/symbol count is not a count of independent missing features. Auth pages are conditionally gated in App.jsx because the diagnostic backend does not implement password/login/register endpoints. This is not evidence of production authentication completion.

Live FR24 corpus completion, FAA registry certification, RLSM source-dependent tests, imagery migration, and physical-device proof remain in the full-program denominator. The two open issue IDs and original source blockers remain in the prior completion report.

## Federation lockstep

All seven canonical repositories were inspected without altering their dirty work. Same-relative-path schema comparisons found 17 byte-identical files, five schema differences, and 13 paths without a corresponding TheHub file. These observations do not prove canonical authority. The ledger preserves exact local heads, remote identities, dirty state, file hashes, key-set intersections/differences, and unresolved comparisons. Shared-contract mutations in this vector: zero.

Before integrating shared-contract PRs #246, #247, #251, #252, #253 or #268: identify authoritative bindings, freeze producer and consumer heads, validate every affected consumer in an isolated checkout, preserve schema differences, and promote compatible revisions together. Do not copy across the six dirty checkouts or silently replace consumer schemas based on names.

## B: restartable validation runner

`maintenance/repair_runner.py` is local developer/CI infrastructure, explicitly classified internal in the GUI capability manifest. It runs a supplied argv plan without shell interpolation, installs nothing, and never fetches sources or publishes changes. Receipts must live outside the source checkout. Gates have unique IDs, bounded process-group timeouts, isolated coverage paths, per-attempt logs and atomic JSON receipts. A lock prevents two runs from owning the same receipt directory. Cancellation terminates the owned child process group.

Resume reuses only PASS receipts with matching source, environment, plan, runtime/dependency fingerprints and intact log hashes. It checks source/dependency drift before and after execution; drift stops the remaining vector. Failed gates rerun while passed gates can be reused. It never converts a local PASS into program completion: `program_status` remains OPEN and `certified` remains false.

The plan must include installed dependency and runtime fingerprint files; a lockfile alone does not establish the installed environment. Freeze package inventories before execution. An intentionally conservative environment digest can invalidate reuse when even a harmless environment variable changes. Missing/corrupt preflight inputs fail rather than being silently ignored. A lock left by machine termination requires checking that its recorded owner has stopped before manually removing it.

Example (use the repository-declared interpreter and a frozen plan):

```sh
.venv/bin/python maintenance/repair_runner.py --repo "$PWD" --plan /absolute/path/validation-plan.json --output /absolute/path/receipts
.venv/bin/python maintenance/repair_runner.py --repo "$PWD" --plan /absolute/path/validation-plan.json --output /absolute/path/receipts --resume
```

Eight regressions cover intact-pass reuse, log tampering, source/plan/environment/dependency changes, failures, source mutation, timeout/missing executable, output/ID/cwd validation, lock ownership and machine-readable receipts. A success-exit dependency mutation fails closed. The live integration plan runs runner/contract/parity tests, Ruff, static parity, and visible-route browser checks; receipts record actual final outcomes.

## Evidence location

Local receipts: `/Users/jotaele/fed-repos/_skywatcher_abc_20260908`. Key files: `pr-reconciliation.json`, `repair-check-annotations.json`, `completion-inventory.json`, `federation-preflight.json`, `federation-contract-comparison.json`, `validation-plan.json`, and `runner-live/result.json`. The final manifest hashes the retained evidence and binds the continuation commit. The initial repair report retains the full Python/frontend/build proof; unchanged source is compared before reusing those artifacts.
