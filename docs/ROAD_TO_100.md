# Road to 100% — SkyWatcher Producer Completion Ledger

Status snapshot for the SkyWatcher airspace/observation producer as a federation
node. This is the honest, leverage-ordered ledger: what is *code-closed* here vs.
what is *genuinely blocked on external data/imagery* and therefore left as a
typed extension point rather than faked.

- **Current completion: ~73%** — the lowest-producing federation node.
- **`ready_for_hub_live_execution: false`** (matches `federation.json`). This flag
  stays `false` until real FR24 captures and a live export run exist; it is a
  data/network gate, **not** a code gate.
- Verification for everything below is **offline only**. No synthetic
  airspace/observation rows were produced — the production export mode's
  "reject synthetic rows" contract is intact.

## Inventory (done)

| Area | State |
|---|---|
| Python modules | 316 files |
| SATIM engine | in-tree, production/test export modes |
| FR24 ingest | in-tree |
| Export contract | test + production modes, synthetic-row rejection |
| Test files | 100 (`tests/`, `tools/**/tests/`) |
| CI workflows | 7 (`ci`, `desktop-build`, `maintenance`, `satim-engine-ci`, `satim-phase2`, `satim-route-findings-ci`, `satim-runtime-smoke-tests`) |

## Code closed in this PR

Pure, offline-computable logic — no network, no new heavy dependency.

1. **SATIM engine GIS join — offline geometric mode.**
   `tools/satim_engine/src/satim_engine/plugins/gis_join.py` previously only
   stamped `BBOX_CONTEXT_ONLY`. It now performs a real, dependency-free spatial
   join when the caller supplies layer bounding boxes: per-point bbox membership
   plus nearest-layer distance (planar degrees), emitting `GIS_JOIN_OFFLINE`
   status with `gis_matched_layers` / `gis_nearest_layer_deg`. The context-only
   path, the empty-frame contract, the `gis_layer_count` column, and the
   never-mutate guarantee are all preserved (existing `test_plugins.py` still
   holds). The geometry primitives live in a new pandas-free module
   `plugins/gis_geometry.py` so the contract is unit-testable without pandas.
   - **Extension point:** swap `gis_geometry` for a geopandas/rtree backend to get
     polygon containment + projected/geodesic distances. Signature is stable.

2. **SATIM engine visual OCR — typed backend extension point.**
   `tools/satim_engine/src/satim_engine/plugins/visual_ocr.py` keeps its
   deterministic offline **filename adapter** as the default (unchanged output:
   `FILENAME_ONLY`, `None` hints) and adds a `backend: VisualOcrBackend`
   parameter. A supplied backend's result is merged over the filename defaults;
   a backend that raises degrades to `OCR_BACKEND_ERROR` without breaking the
   batch. This is the single clean seam for a production OCR engine.
   - **Extension point (needs an unavailable engine, offline-blocked):** a real
     OCR backend (pytesseract / easyocr / hosted vision model). Not vendored —
     inject it via the `backend` parameter.

3. **Focused unit tests (pure, no network).**
   - `tools/satim_engine/tests/test_gis_geometry.py` — bbox parsing, membership,
     distance, layer resolution, and the pandas-facing join (pandas cases guarded
     with `importorskip`).
   - `tools/satim_engine/tests/test_visual_ocr_backend.py` — default passthrough,
     backend merge, label override, and error degradation.

## Already code-complete on `main` (verified offline in this audit)

These were closed by earlier increments; this audit **verified** them rather than
rewriting them (rewriting correct, tested code would only risk regressions):

- **SATIM Phase-2 calibration modules** — `fr24/calibration/`:
  `satim_raster_candidate_extraction.py` (`detect_raster_candidates` +
  `candidate_from_detection` → `satim.visual_ledger.v1`),
  `satim_multidate_validation.py` (single-still block, cross-epoch persistence),
  `satim_gis_overlay.py` (spatial-metric normalization + infrastructure-explains
  flag). **9/9 Phase-2 contract tests pass offline.**
- **RLSM `flight_track_features`** — `fr24/rlsm_flight_track.py`: offline
  speed/heading heuristic (`_classify_screenshot`) at `confidence=0.3`, with an
  optional CV vectorizer pass when an image root is supplied. (The stale
  "deferred" docstring in `rlsm_extractors.py` has since been corrected — see the
  audit increment below.)
- **Geo-anchor guard** — `fr24/rlsm_extractors.py::seed_geo_anchors` already
  guards cleanly on missing `data/rlsm/georef_anchors.csv`
  (`{"seeded": 0, "reason": "georef_anchors.csv not found"}`). Supplying that CSV
  is a **data** task, not a code task.

## Closed in the multi-repo federation audit increment

Pure, offline-computable logic — no network, no new heavy dependency. These
close three of the four "Remaining — offline code" items below.

1. **Phase-2 calibration modules wired into a runnable pipeline stage.**
   `fr24/calibration/run_phase2.py` is a thin driver (with a
   `python3 -m fr24.calibration.run_phase2` entry point) that reads an AOI
   detection fixture → `detect_raster_candidates` → `patch_candidate_with_gis_scores`
   → `validate_candidate_across_dates` → a `satim.visual_ledger.v1` CSV. It
   **reuses** the three proven Phase-2 functions verbatim (no reimplementation),
   does no image IO / network, and produces calibration-candidate rows — not a
   production airspace export. Fixture: `tests/fixtures/satim_phase2/aoi_detections.json`
   (precomputed detections / GIS metrics / multi-date records only). End-to-end
   test: `tests/test_satim_phase2_run_phase2.py` (added to the `satim-phase2` CI
   job).
   - **Extension point:** swap the fixture loader for a real detection / GIS /
     imagery backend; the driver's input mapping shape and CSV columns stay stable.

2. **Deterministic filename-hint `VisualOcrBackend` (bundled, opt-in).**
   `tools/satim_engine/src/satim_engine/plugins/visual_ocr_filename_backend.py`
   parses callsign / tail / timestamp tokens from the file *name* with tight,
   boundary-anchored regexes and merges through the existing `backend` seam in
   `visual_ocr.py`. It is **not** in the default path: the no-backend
   `extract_visual_metadata` `FILENAME_ONLY` / `None`-hints contract is unchanged
   byte-for-byte (test-pinned). Tests:
   `tools/satim_engine/tests/test_visual_ocr_filename_backend.py`.

3. **Stale "deferred" docstring retired.** `fr24/rlsm_extractors.py` no longer
   claims `flight_track_features` is "deferred pending route_extractor
   integration" — it documents that the table is populated by
   `fr24/rlsm_flight_track.py`. A golden-row fixture test
   (`tests/test_rlsm_flight_track.py::test_golden_rows_per_screenshot`) pins the
   exact per-screenshot row the runner writes against a tiny seeded SQLite DB
   (offline, no network).

## Remaining — offline code (leverage-ordered checklist)

Highest leverage first. All offline-computable; none require network.

1. **Real geometry backend behind `gis_geometry`.** Polygon containment and
   projected distances (geopandas/shapely/rtree) behind the stable helper
   signatures. Gated on the `requirements-geo.txt` optional stack. Left as a
   documented extension point.

## Remaining — data / network-blocked (`ready_for_hub_live_execution: false`)

Left as typed extension points; **not** faked. Each needs an external artifact.

- **Live FR24 captures + a live production export run.** The producer cannot flip
  `ready_for_hub_live_execution` to `true` until real captures exist and a
  production-mode export (synthetic rejection on) completes. Blocked on operator
  supplying captures.
- **GEBCO terrain** ingest — bathymetry/terrain layer still in the spiderweb
  archive branch, unported. Extension point: `gis_geometry` `terrain_crossing`
  feeds already exist in the visual-ledger schema.
- **RAG / earthgpt** enrichment — unported from the spiderweb archive branch.
- **Satellite imagery ingest** — unported from the spiderweb archive branch; the
  Phase-2 raster extractor consumes *precomputed* detections precisely so this
  can be added without changing the contract (see extension point #1 above).
- **ILAP intake** — needs locally-supplied FR24 screenshots for OCR; the
  `visual_ocr` backend seam is the plug-in point.
- **`georef_anchors.csv`** — supply the CSV to activate `seed_geo_anchors`.

## Honest completion split

- **% closed (code):** the offline-computable code surface for this producer is
  effectively closed — Phase-2 calibration (verified), RLSM flight-track +
  geo-anchor guard (verified), and the two SATIM engine plugins (closed here).
  The remaining *code* items above are wiring/optional-backend polish, not
  missing core logic.
- **% data-blocked:** the residual gap to 100% (roughly the ~27% below full) is
  dominated by **data/network** artifacts — live FR24 captures + live export,
  and the unported spiderweb-archive layers (GEBCO, RAG/earthgpt, satellite,
  ILAP screenshots). These are gated on external inputs, not on code in this
  repository.
