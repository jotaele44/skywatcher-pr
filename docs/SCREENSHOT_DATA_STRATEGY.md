# FR24 Screenshot Data — extraction strategy

How to get the most value per screenshot from the ~15k-image FR24 corpus (11,926 already
ingested into the RLSM store; `data/rlsm/HANDOFF.md`). Ordered by leverage — each item names
the exact code it builds on. The structural finding behind the ordering: **three screenshot
pipelines exist side by side and don't share their best components** — the legacy
`screenshots` table lane, the mature RLSM sqlite lane, and a disconnected Claude-vision CSV
lane — so the highest returns come from wiring what already works into the paths that need it,
not from new extraction research.

## 1. Promote the per-screenshot affine geocoder to the shared calibration (do first)

Every legacy observation is stamped with a fixed guess — `fixed_pr_bounds`, confidence 0.65,
estimated error 1,500 m (`fr24/screenshot_inventory.py:195-197`) — which means
`build_producer_package.py` can never emit a `located` observation (its floor is
coordinate confidence ≥0.8) and the production stream stays "approximate" forever.
Meanwhile `scripts/rlsm_geocode_unlabeled.py` **already implements** a working per-screenshot
4-parameter affine fit from ≥2 vocabulary-matched labeled pins.

**Action:** lift that transform into the shared calibration used by `fr24/event_export.py`
(currently `GeoCalibration(mode="fixed_pr_bounds")`) and `scripts/build_producer_package.py`,
writing real per-image `coordinate_confidence`/`estimated_error_m`. Expected effect: 10–50×
error reduction on calibratable frames, observations crossing the `located` floor, and a real
production package from the existing corpus — this is the screenshot-side path to flipping
skywatcher's live gate *without waiting for FR24 CSV quota*.

## 2. Unify the three lanes on the RLSM store

- Point `build_producer_package.py` at RLSM-derived rows (or sync RLSM extractions back into
  the legacy `screenshots` table) so producer packages inherit zone-OCR, pin, and anchor
  quality signals instead of inventory-time defaults.
- Retire the disconnected vision-CSV lane (`scripts/fr24_vision_ingest.py` → `priis.db`) by
  writing its 12 extracted fields into RLSM `ocr_observations`-adjacent tables instead. The
  vision pass is cheap (~$20–25 for the full corpus at Haiku; `fr24_vision_ingest.py:8`) and is
  the best **second opinion** for frames where Tesseract OCR confidence <50 (the existing
  review-queue threshold, `fr24/rlsm_extractors.py:448-449`) — run it on the low-confidence
  slice first, not the whole corpus.
- Join `aircraft_registry` (FAA registry table, `data/rlsm/schema.sql`) and `manual_flight_log`
  ground truth into the extractors so every N-number resolves to owner/type and every
  operator-logged flight cross-validates OCR.

## 3. Fuse same-flight screenshots and match endpoints

Temporal-wave grouping already clusters same-aircraft observations across time
(`docs/FR24_OCR_ANALYSIS_VECTOR.md`), but the Spiderweb adapter still exports every frame as an
isolated event (`num_screenshots=1` hardcoded, `fr24/spiderweb_adapter.py:151`). Fusing a wave
into one multi-point observation multiplies evidential value: consistent reg + advancing
positions across N frames is far stronger than N independent single-frame candidates, and it
feeds the corridor/loiter scoring in `ilap_airspace_bridge.py` directly. Pair this with the
schema'd-but-unbuilt `flight_endpoint_event` match against the airport registry
(`docs/FR24_NON_SYNTHETIC_EXPORT_PLAN.md` check #3, `configs/airport_registry.yaml`) so waves
gain origin/destination semantics.

## 4. Vectorize the on-screen track polyline (the biggest untapped signal)

The route line drawn in every screenshot is currently discarded: `fr24/rlsm_flight_track.py`
derives `path_shape`/`has_hover` from speed/heading fields only and leaves `has_loop/orbit/gap`,
`track_length_px`, `follows_coast`, `near_airport` at 0/NULL ("we couldn't look" — its own
honest-limits note, lines 12-20; the module names the CV classifier a deferred follow-up,
tracked as "B-flight-track").
A color-mask + polyline-trace CV pass (the FR24 track color is consistent) would unlock
loiter/orbit detection — precisely the behaviors the ILAP scoring weights highest
(`ilap_airspace_bridge.py` loiter weight 0.25). This is the largest new-information win, but
it's real CV work — do it after 1–3, which are wiring, not research.

## 5. Triage review queues by cluster, not by item

The review backlog is ~526,918 unlabeled pin candidates (~40–50/image; `data/rlsm/HANDOFF.md`).
Nobody reviews half a million items — but `scripts/rlsm_cluster_unlabeled_pois.py` already
groups them by recurring map-pixel position. Review **clusters** (one decision covers hundreds
of recurrences), starting with clusters that co-occur with high-confidence aircraft
observations. Same principle for SATIM: the calibration engine is built and conservative but
starved at 12 ground-truth labels (`frontend/public/satim/moca_fr24_2025.summary.json`) — every
operator labeling hour should go to the existing harvest harnesses
(`scripts/satim_harvest_review_labels.py`, `scripts/fit_satim_calibration.py`) rather than ad-hoc
review.

## 6. Spend the scarce resources where they compound

- **FR24 CSV quota (25/day, `scripts/fr24_harvest.py`)**: aim captures at flights that already
  have screenshot waves — each CSV then ground-truths the affine geocoder (#1) and the track
  vectorizer (#4) against exact timestamped coordinates, instead of adding isolated tracks.
- **Operator-Mac vs cloud split** (`docs/RUNBOOK_FR24_DATA_LOAD.md`): OCR/DB builds stay local
  (~2h at 4 workers); everything downstream of the sqlite — extractors, coverage reports,
  bridges, producer packages, SATIM scoring — runs in CI. Ship the small sqlite-derived reports,
  never the corpus.
- **Vision budget**: low-OCR-confidence slice first (#2), then the unlabeled-pin clusters that
  survive #5 triage.

## Sequence summary

| # | Investment | Type | Unlocks |
|---|---|---|---|
| 1 | Affine geocoder → shared calibration | wiring | `located` observations; production package from existing corpus |
| 2 | Unify lanes on RLSM store | wiring | registry/ground-truth enrichment everywhere; targeted vision second-opinions |
| 3 | Wave fusion + endpoint matching | modeling | multi-frame evidence; origin/destination semantics |
| 4 | Track-polyline CV | research | loiter/orbit/gap detection feeding ILAP |
| 5 | Cluster-first review + SATIM label growth | process | review throughput ×100s; calibration un-starved |
| 6 | Quota/vision/compute allocation | process | every scarce unit ground-truths #1/#4 |
