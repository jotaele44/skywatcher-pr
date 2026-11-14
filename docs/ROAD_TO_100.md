# Road to 100 — normalized federation score

**Audit date:** 2026-08-04  
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

> **State review 2026-11-13.** The score and table below are the 2026-08-04 audit and are
> superseded: `main` has moved, and they have not been re-scored. Current item states are in
> `docs/unfinished_implementation_ledger.v1.json`; the current audit and priority order are in
> `docs/AUDIT_AND_OPTIMIZATION_STRATEGY_2026-11-13.md`.

## Normalized score on 2026-08-04: 65.05 / 100

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
- PR #176 (SG0 governance) was closed unmerged on 2026-09-03; SG1–SG4 stay blocked until the maintainer re-ballots SG0 or retires the track.
- PR #173 (rescued patch material) was closed unmerged on 2026-09-03 and is no longer pending.
- Real FR24 captures, production export, geo anchors, terrain/imagery layers and operator receipts remain incomplete.

## Priority exit sequence

1. Execute the complete local screenshot corpus with zero false binding and bounded uncertainty.
2. Preserve deterministic replay and provenance boundaries through operator receipts.
3. Finish replacing the obsolete `places.geojson` dependency: the tracked gazetteer is in place, but `scripts/rlsm_spatial_map.py` and `scripts/rlsm_diacritic_repoi.py` still read the old file.
4. Supply real FR24 captures and run a production-mode export with synthetic rejection enabled.
5. Done: #173 was closed unmerged. Do not apply its patch files wholesale.
6. Certify standalone packaging for the merged isolated-clone runtime.
7. Keep SG1–SG4 blocked until SG0 is certified and each later phase has an independent implementation ballot.
8. Re-vendor the federation entity and alert schemas, and land FAA Registry Certification v1 (#240), the ILAP corpora (#282) and the detector stack (#279).

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Governance-only artifacts receive no runtime-completion credit.
