# Road to 100 — normalized federation score

**Audit date:** 2026-08-04  
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

## Current normalized score: 65.05 / 100

| Dimension | Weight | Score | Weighted |
|---|---:|---:|---:|
| Code completeness | 20 | 86 | 17.20 |
| Main-branch availability | 15 | 67 | 10.05 |
| CI enforcement | 15 | 72 | 10.80 |
| Data materialization | 15 | 55 | 8.25 |
| Operator verification | 15 | 45 | 6.75 |
| GUI completeness | 10 | 75 | 7.50 |
| Federation readiness | 10 | 45 | 4.50 |

The former ~73% figure combined code present on main with data-blocked and candidate-only work. The normalized score discounts major capabilities that remain in draft PRs or have not run against the operator corpus.

## State reconciliation

- SATIM, FR24/RLSM foundations, OCR preprocessing provenance and ontology v2.0 governance are on `main`.
- The analysis lens registry (`docs/ANALYSIS_LENS_REGISTRY.md`) moves analytical
  parameters from code into `configs/analysis/`, surfaces them at `/analysis`, and adds
  the first backend/GUI parity test in the repo. The **GUI completeness** and **CI
  enforcement** rows above are not re-scored here — that is an audit judgment against the
  operator corpus, not something this change can assert about itself. What it does change
  is that a skipped analytical check is now distinguishable from one that ran and found
  nothing, which is a precondition for scoring operator verification honestly at all.
- PR #171 is merged current-main aircraft spatial truth; full operator-corpus execution remains pending.
- PR #170 is merged current-main deterministic multisensor replay.
- PR #172 is merged current-main isolated-clone runtime.
- PR #176 is SG0 governance only and activates no runtime, schema or threshold.
- PR #173 is rescued unapplied patch material and obsolete local dependency state, not implementation authority.
- Real FR24 captures, production export, geo anchors, terrain/imagery layers and operator receipts remain incomplete.

## Priority exit sequence

1. Execute the complete local screenshot corpus with zero false binding and bounded uncertainty.
2. Preserve deterministic replay and provenance boundaries through operator receipts.
3. Replace the obsolete `places.geojson` dependency with tracked gazetteer and geo-anchor inputs.
4. Supply real FR24 captures and run a production-mode export with synthetic rejection enabled.
5. Dispose of #173 by path-level adjudication; do not apply patch files wholesale.
6. Certify standalone packaging for the merged isolated-clone runtime.
7. Keep SG1–SG4 blocked until SG0 is certified and each later phase has an independent implementation ballot.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Governance-only artifacts receive no runtime-completion credit.
