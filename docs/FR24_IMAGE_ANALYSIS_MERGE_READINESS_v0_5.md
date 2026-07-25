# FR24 Image Analysis Skill — Merge Readiness v0.5

## Target

- Pull request: #98
- Requested head: `7d8d01afae912de2d1cf1f3d4dda36679fe3938f`
- Branch: `codex/skywatcher-fr24-image-analysis-skill-v0-1`
- Private fixture: `IMG_0218 (Merged).pdf`
- Expected SHA-256: `8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf`
- Expected size: 22,210,568 bytes
- Expected pages: 39

## Execution disposition

The private fixture binary was not available to the GitHub runner or repository checkout. The accessible file-library records confirm the fixture name, SHA-256, size, and 39-page baseline, but do not expose reusable binary bytes to the repository runtime. Therefore, the requested two forensic executions were not represented as completed.

No post-v0.4 candidate count, normalized digest, UI-suppressed count, non-UI count, or dark-surface count is asserted in this report.

## Verified prior baseline

The existing operator-local baseline supports:

| Gate | Baseline status |
|---|---|
| PDF page count | 39 / 39 |
| Source accounting | 100% |
| Frame SHA-256 coverage | 100% |
| Source SHA-256 | Match to expected hash |
| Route signal | Pages 1, 3, 4, and 5 |
| Geographic status | `not_registered` |
| Fixed-bounds promotion | false |
| Device/replay time separation | enforced |

## v0.4 code and CI status

The v0.4 accounting and false-positive controls are covered by repository tests and passed the full PR workflow matrix:

- Skywatcher CI run 432: success
- SATIM Runtime Smoke Tests run 89: success
- Federation template drift run 60: success

Covered contracts include:

- stable finding IDs before export;
- one contradiction-ledger row per finding;
- one review row per unresolved or candidate finding;
- header-only zero-finding ledgers;
- deterministic ledger ordering;
- UI-margin seam suppression;
- score-threshold seam gating;
- repeat-view metadata fields.

## Required private-fixture command

Run from a checkout pinned to the PR head with the exact private fixture bytes:

```bash
python -m fr24_image_skill run "IMG_0218 (Merged).pdf" --output-dir /tmp/pr98-v04-run-1 --mode forensic
python -m fr24_image_skill run "IMG_0218 (Merged).pdf" --output-dir /tmp/pr98-v04-run-2 --mode forensic
```

Then verify:

```text
PDF_PAGE_COUNT=39
SOURCE_SHA256=8e5307c999d53e3ea0185caaa33cbbe2a8e994e271b34ac31712846b15d5aecf
SOURCE_ACCOUNTING=100_PERCENT
FRAME_HASH_COVERAGE=100_PERCENT
NORMALIZED_DIGEST_RUN_1=NORMALIZED_DIGEST_RUN_2
FINDING_TO_CONTRADICTION_ACCOUNTING=100_PERCENT
UNRESOLVED_TO_REVIEW_ACCOUNTING=100_PERCENT
RAW_TRACK_FEATURES>=1
REGISTERED_TRACK_STATUS=NOT_REGISTERED
```

## Merge readiness matrix

| Domain | Gate | Status | Merge impact |
|---|---|---|---|
| Source integrity | Fixture hash and page baseline established | PASS | None |
| Code quality | Full CI matrix | PASS | None |
| Stage controls | Stage 1 and Stage 2 freeze order | PASS | None |
| Determinism | Synthetic and prior fixture baselines | PASS / PARTIAL | Private post-v0.4 rerun pending |
| Finding accounting | 100% row-level contracts in tests | PASS | None |
| False-positive control | Threshold and UI-margin tests | PASS | None |
| Route preservation | Prior fixture pages 1/3/4/5 | BASELINE PASS | Post-v0.4 confirmation pending |
| Geographic restraint | `not_registered` without affine fit | PASS | None |
| Safety boundaries | No purpose or flight-intent inference | PASS | None |
| Private fixture v0.4 execution | Two forensic runs | NOT EXECUTED | Final empirical merge evidence pending |
| Candidate comparison | v0.3 versus v0.4 counts | NOT AVAILABLE | Cannot quantify reduction yet |

## Adjudication

**Code readiness:** READY FOR REVIEW.

**Empirical private-fixture readiness:** INCOMPLETE. The remaining requirement is narrow and reproducible: supply the exact fixture bytes to a local or CI runtime, execute twice, and append the resulting manifests and count comparison.

PR #98 should remain draft and unmerged until either:

1. the private fixture rerun is completed and the matrix is updated; or
2. the user explicitly waives the private-fixture rerun as a merge requirement.
