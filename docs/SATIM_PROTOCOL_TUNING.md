# SATIM Protocol / Calibration Tuning

Outcome of the analysis-protocol audit. This change tightens the SATIM protocol
to one canonical path and adds a reproducible calibration harness, without
altering default detection behaviour.

## Tier-1 — safe, behaviour-preserving

- **One canonical engine.** `fr24/satim_engine_core.py` was a slimmer duplicate
  that omitted artifact-assessment / provider / ledger enrichment, so a run's
  output differed by entrypoint. It is now a thin re-export of the canonical
  `fr24/satim_engine.py`; both entrypoints emit identical, fully-enriched output.
- **Detector-band consistency.** `satim_water_feature.py` confidence bands
  aligned to the detector-family standard (HIGH ≥0.70, MEDIUM ≥0.40; previously
  0.75/0.45).
- **Readiness integrity.** `PRIIReadinessEngine.PRODUCTION_READY` docstring now
  matches the code (candidate_count is *reported*, not gated); an opt-in
  `min_operational_candidates` floor enforces a minimum when set (default off,
  preserving prior behaviour). `final_status` + `READY_FOR_OPERATIONS` and
  `candidate_count` are now declared in `schemas/prii_readiness_report.schema.json`.
- **Reproducible fit harness.** `satim_fit.py` gained a CLI
  (`--ground-truth CSV [--fp-classes YAML --out YAML]`) that derives
  `scoring_adjustments` + `promotion_thresholds` from labeled outcomes
  (precision targets 0.50/0.75/0.90). `tests/test_satim_fit.py` runs it on a
  synthetic ground-truth in CI, asserting deterministic, monotonic thresholds —
  so tuning becomes a *data* step, not a code change.
- **Dead-knob doc.** Engine C `spatial_threshold_meters` marked reserved/no-op in
  `tools/satim_engine/config/satim_default.yml` (visual metadata carries no
  coordinates yet).

## Tier-2 — flag-gated (default = current behaviour)

- **L5 classifier selection.** New manifest option `l5_mode`:
  `tile_seam_shadow` (default) or `synthetic_boundary` (explicit-weight feature
  classifier). `run_l5()` normalizes the payload to the canonical
  `L5_tile_seam_shadow` slot so readiness aggregation is unaffected.
- **Fuzzy L3 scoring.** New manifest option `l3_fuzzy` (default `false`). When
  enabled, `l3_ocr_scoring` awards OCR-confusable (O/0, I/1, …) and single-edit
  credit for text fields; integers are never fuzzy. Default path is
  byte-identical to today.

## Deferred (recorded, not invented)

- **Strict tile-seam AND-gate** (`SATIM_TRACK_LINE_VS_TILE_SEAM_RULES.md`) is
  *not* offered as an `l5_mode`: it requires a `screen_locked_score` feature the
  feature engine does not yet produce. Implementing that feature is the
  prerequisite; a broken `strict` mode was deliberately not shipped.
- **Empirical thresholds.** The fit harness exists and is CI-tested, but the
  production `scoring_adjustments`/`promotion_thresholds` are still the hand-set
  v1 values — deriving measured ones needs an expanded, sanitized ground-truth
  set (the control set is ~4 rows). Data-gated.
- **`registration_watchlist.yaml` duplication.** The `config/` (singular) and
  `configs/` (plural) copies have *diverged* into different lists (the FR24 docs
  point to the singular; the plural names a consumer absent from this repo).
  Neither is loaded by Python here; de-duping was deferred rather than risk
  deleting diverged content — an unresolved ownership question to confirm.
- **A real `validated` provider profile** (populated `class_thresholds`) — the
  `generic_screenshot_v1.json` stub still has empty thresholds. Data-gated.
