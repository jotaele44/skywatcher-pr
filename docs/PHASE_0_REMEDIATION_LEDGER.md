# Phase 0 Review Remediation Ledger

## Target

- Pull request: `#110`
- Final-review remediation vector: `REMEDIATE_SKYWATCHER_FINAL_REVIEW_FINDINGS_v1`
- Current-main merge parent: `e7eab8b496a0dfc40fa4de34f02a18466ea75a0d`
- Certified remediation code head: `b1fa903f3ab7d48c2d298d9978fd31404a129a5e`
- Pull-request disposition: draft, open, unmerged

## Scope preservation

- Current `main` is a true merge parent and the branch is zero commits behind.
- No remediation-authored changes exist under `frontend/` or production `data/` paths.
- Current-main governance, RLSM pipeline, runbook, schema, and placeholder-directory changes were preserved during reconciliation.
- Public analytical schemas remain compatible.
- Mission, intent, target, wrongdoing, causality, and operational-purpose inference remain prohibited.
- `operational_cueing=false` remains enforced.

## Final-review finding closure

| Finding | Remediation | Evidence gate |
|---|---|---|
| Identity fields activated when `verified_fields` was merely nonempty | Added per-field activation through `_verified_identity_fields`; each activated field requires source URI, source record ID, capture time, and SHA-256 | Incomplete-provenance and selective complete-provenance regression tests |
| Ordinary flight-history rows could populate aircraft type/operator | Database enrichment is limited to observed flight count, first-seen time, and last-seen time | Populated-DB test proves aircraft type, owner, and operator remain unknown |
| Committed dependency lock was incomplete and not drift-gated | Generated the lock with the exact pinned `uv pip compile` command and changed CI to require byte-for-byte equality with fresh resolver output | First pass produced the resolver artifact and failed drift as designed; later lock jobs succeeded |
| Archive rollback existed without failure-path certification | Added injected temp-to-target promotion failures and verified original-target restoration plus temp/backup cleanup | Canonical and standalone SATIM rollback tests |
| `desktop/setup.py` used ambiguous package and top-level import forms | Replaced dual imports with one package import and an `importlib` direct-script fallback | Python CodeQL analysis succeeded and the alert thread auto-resolved |
| Rollback tests imported each archive module through two forms | Replaced mixed module/from imports with one module import and local aliases | Both CodeQL alert threads auto-resolved on code head `b1fa903f` |
| `main` advanced during remediation | Created a true two-parent merge, explicitly reconciled `.gitignore`, README, and the RLSM geocoder, and preserved all other current-main files byte-for-byte | `behind_by=0`, mergeable pull request, current-main workflow set green |

## Security boundaries

Aircraft identity is fail-closed per field. Registry membership, callsign structure, aircraft type, route geometry, timing, and ordinary flight-history metadata cannot establish owner, operator, role, mission, schedule, target, or typical operating area. Unproven fields remain `Unknown`.

Flight-history enrichment is observational only: count, first-seen timestamp, and last-seen timestamp. Active profiles always keep role as `Unknown (not inferred)`, mission lists empty, and operational-pattern cueing absent.

Archive extraction is validation-first, stream-bounded, no-replace by default, and recoverable. Explicit replacement keeps the original target in a backup until promotion succeeds; injected promotion failures restore the original and clean temporary state.

Diagnostic writes remain disabled by default and require both `PRII_ENABLE_WRITES=true` and a matching bearer token. IDs are server-owned and immutable, payloads are bounded, and repository files are never mutated by the process overlay.

## Dependency-lock evidence

The first synchronized workflow pass generated `resolved-lock-be98653a17955a11ad1a8be193a1d438b6124e29` and failed only the deliberate full-drift comparison. The generated lock included the complete declared development, API, and federation dependency set, including `build`, `ruff`, and `mypy`, plus exact TheHub references at `f00f2da0e6abcc885a8133e5c8b7aeb9756f5df8`.

That resolver output was committed unchanged as `requirements.lock`. Subsequent lock jobs regenerated the same normalized file and passed `diff -u requirements.lock /tmp/resolved.lock`.

## Code-head certification

All eleven workflow families completed successfully on certified code head `b1fa903f3ab7d48c2d298d9978fd31404a129a5e`:

- Backend core — run `30310474821`
- Skywatcher CI — run `30310474788`
- CodeQL — run `30310474791`
- Secret scan — run `30310474805`
- pip-audit — run `30310474831`
- Federation template drift — run `30310474803`
- desktop-build — run `30310474809`
- SATIM Engine CI — run `30310474794`
- SATIM Route Findings CI — run `30310474801`
- SATIM Runtime Smoke Tests — run `30310474800`
- SATIM Phase 2 Contracts — run `30310474795`

Documentation-only successor heads must rerun every workflow applicable to their changed paths. The pull-request body is the authoritative record of the latest evidence head, final workflow conclusions, and review-thread closure.
