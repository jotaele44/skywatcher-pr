# Skywatcher bounded bug-fix saturation — 2026-09-08

Status: **local repair vector PASS; full program OPEN; hosted verification BLOCKED**.
This is not a universal exhaustion or production certification claim.

## Scope and preservation

Repository: `jotaele44/skywatcher-pr`. Base: `39e1fb297e24cd9017167a8725b40e73dd0349e4`.
Repair branch: `repair/skywatcher-saturation-20260908`.
The repair incorporates all 14 dirty/untracked source files preserved from the canonical checkout, including its unfinished ZIP-inspired shell. Their original bytes remain unchanged in the canonical checkout and in the preservation receipt. No legacy GUI baseline was relaxed. No PR was merged or closed.

Local evidence directory: `/Users/jotaele/fed-repos/_skywatcher_saturation_20260908`.
The terminal receipt manifest records file hashes and the eventual repair commit; logs are local artifacts, not hosted CI evidence.

## Corrections

- Failed or malformed collection loads remain visibly incomplete, retain previous good records, and expose retry. Load generations prevent stale requests from overwriting newer data or confirmed writes.
- Review status, notes, captures, and bulk edits wait for confirmed server responses. Rejections remain visible; draft notes and failed selections survive retry. Notes explicitly describe server-session persistence.
- Browser storage failures have a session fallback; removal tombstones prevent stale token revival. Replacing or clearing credentials also clears the startup URL-token snapshot used by the request client. FastAPI rejection reasons reach the UI.
- Spatial matching rejects missing/nonfinite/out-of-range coordinates, filters containment before choosing a candidate, preserves containing candidate sets, and leaves equal-distance ties unresolved. Empty results serialize without Infinity. Spatial candidates never become identity bindings.
- Cross-domain overlap validates thresholds, confidence, and timezone-bearing timestamps. Numeric scoring and schedule comparisons reject malformed inputs safely.
- Configured frontend and Python type checks pass through explicit types and corrected narrowing. The shared Federation React declaration is source-hash guarded and has positive/negative compile-time contracts. CI now gates both checks.
- Importer subprocess tests use the active Python interpreter. Browser verification uses isolated ports and explicit interpreter setup. Capability mappings and visible-route tests were updated together.

## Terminal validation

| Gate | Result | Receipt |
|---|---|---|
| Full Python core suite, Python 3.12.12 | 1,574 passed; 21 skipped; 2 deselected; 68.03% coverage, above required 55% | `backend-terminal.log`, `.xml`, `coverage-core.sqlite` |
| Optional imagery/geospatial extension, expanded locked environment | 239 passed; zero skipped | `optional-tests.log`, `.xml`, `python-optional-environment.txt` |
| Frontend unit suite | 68 passed, 10 files | `frontend-test-auth-final.log` |
| Configured TypeScript scope | zero errors | `frontend-typecheck-terminal-final.log` |
| Configured mypy scope | zero errors, 91 files | `mypy-verified.log` |
| Browser visible-route/manifest tests | 15 passed, covering all 14 visible routes | `gui-e2e-all-routes.log` |
| Browser mobile/error/retry/bulk flows | 6 passed | `browser-auth-final.log` |
| Console runtime | 5 passed | `console-terminal.log` |
| Ruff / ESLint / production build / lock check | see terminal receipt | `ruff-terminal.log`, `frontend-lint-terminal-final.log`, `frontend-build-terminal-final.log`, `lock-verified.log` |
| Static GUI parity ratchet | PASS: 1,955 candidates; 70 mapped; 1,885 legacy; zero new findings or manifest issues | `gui-parity-terminal.json` |
| Export positive/negative and calibration | PASS, including rejection of synthetic rows | `export-test-independent.log`, `export-negative-independent.log`, `calibration-independent.log` |

The optional run overlaps the core suite: do not add their pass totals as unique tests. It resolves two dependency-related skip categories from the core run. Nineteen source-dependent skips remain: fifteen require the RLSM database absent from this checkout and four require exact C654 source bytes. Two configured deselections remain outside the run. The skip ledger preserves reasons. Absent checkout inputs do not prove global source absence.

Coverage measures the core environment only. Warnings remain (including upstream/deprecation warnings); this is not warning-free validation. Local Node 26 and Python 3.12 checks do not certify every CI runtime, OS, or physical device. Existing configured type-check exclusions remain; zero configured diagnostics is not whole-repository static typing.

## Full-program residue

1. Reviewed, materially complete non-synthetic FR24 inputs, identity adjudication, and capture geometry review remain necessary. The existing three-screenshot proof is approximate and bounded.
2. TheHub imagery/model migration still requires parity, dual-run, rollback, GUI, and retirement gates under ADR 0006.
3. The GitHub snapshot contains 23 open PRs and two open issues. Their implementations/dispositions remain in the full-program denominator; they were not integrated by this repair.
4. Static GUI inventory still has 1,885 legacy findings. Ratchet success proves no new unclassified additions, not full capability parity.
5. Hosted check-run `102055268345` reports the account locked due to billing and the job not started. Repeated source changes or reruns cannot establish hosted success while runner admission is blocked.

`federation.json` continues to report `live_execution: false`. The historical eight-item implementation ledger is routing evidence, not a newly computed readiness score. No CERTIFIED label or fabricated completion percentage is assigned.

## Reuse and repeatability

Preserved failed attempts include missing browser storage methods, absent literal `python`, browser port collision, initial type errors, a hash test using the wrong DOM environment, and a preliminary coverage result invalidated by concurrent coverage writers. Terminal runs supersede them without deleting their receipts. Reuse passed artifacts when downstream gates fail; do not refresh source inputs implicitly.

For replay, use frozen dependency manifests and the recorded Python environment, run `pytest` with a unique coverage output path, then the configured frontend unit/type/lint/build scripts, console tests, static parity and both Playwright configurations. Keep external corpus-dependent checks visibly skipped or blocked until their exact inputs are supplied. The source manifest and receipt hashes distinguish a repeat run from evidence on changed code.
