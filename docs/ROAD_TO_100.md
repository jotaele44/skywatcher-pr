# Road to 100% — SkyWatcher Producer Completion Ledger

Status snapshot for the SkyWatcher airspace/observation producer as a federation
node. This is the honest, leverage-ordered ledger: what is *code-closed* here vs.
what is *genuinely blocked on external data/imagery* and therefore left as a
typed extension point rather than faked.

- **Current completion: ~73%** — the residual gap is primarily external data and live-operation evidence.
- **`ready_for_hub_live_execution: false`** (matches `federation.json`). This flag
  stays `false` until real FR24 captures and a live export run exist; it is a
  data/network gate, **not** a code gate.
- Verification below does not fabricate live observations. Production export
  retains its synthetic-row rejection contract.

## Inventory

Counts and controls reconciled 2026-07-27 against current `main` plus Phase 0 review remediation.

| Area | State |
|---|---|
| Python modules | Mixed root/src compatibility layout with canonical PEP 517 `src/skywatcher` package |
| SATIM engine | In-tree, production/test export modes, independently distributable package |
| FR24 ingest | In-tree |
| Export contract | Test + production modes, synthetic-row rejection |
| Previous full-assets baseline | **807 passing**, 13 skipped |
| Phase 0 data-independent baseline | **754 passing**, 36 skipped, 53 capability tests deselected |
| Nested tool packages | **60 passing** at original Phase 0 certification; later CI remains green after added archive tests |
| CI workflows | 13: `backend-core`, `ci`, `centinelas-handoff`, `codeql`, `desktop-build`, `maintenance`, `pip-audit`, `satim-engine-ci`, `satim-phase2`, `satim-route-findings-ci`, `satim-runtime-smoke-tests`, `secret-scan`, `template-drift` |
| Frontend | Current-main frontend preserved byte-for-byte; lint/build remains gated; no remediation-authored frontend changes |
| Python packaging | PEP 517 installable root with `skywatcher` CLI; no sibling checkout required for core |
| Dependency integrity | Exact TheHub VCS pins, immutable lock checks, pip-audit, Dependabot |
| Security | CodeQL, secret scan, safe archive contract, write-disabled diagnostic API |
| Lint / type | Ruff and mypy visible as report-only jobs; coverage floor remains gated |

## Phase 0 review remediation closed

The independent review blockers were corrected without lowering existing controls:

1. **Current-main reconciliation.** The branch contains current `main` as merge parents and preserves its security, dependency, coverage, and frontend changes.
2. **Installed CLI contract.** Repository schema validation fails closed when assets are absent and is tested from an isolated wheel install outside the checkout.
3. **Archive safety.** Extraction is path-safe, stream-bounded, no-replace by default, and recoverable on explicit replacement.
4. **Diagnostic API integrity.** Writes require explicit enablement and a bearer token; IDs are server-owned and immutable; payloads are bounded.
5. **No-intent boundary.** Aircraft matching is exact; legacy identity fields remain inactive without field-level provenance; role and mission remain unresolved.
6. **Deterministic handoff.** Source export and hygiene share one policy and preserve executable launcher modes.
7. **Coverage-tier separation.** Backend-core remains data-independent while full CI runs data-capability tests to retain the 55% coverage floor.

See `PHASE_0_REMEDIATION_LEDGER.md` and `PHASE_0_REVIEW_CLOSURE.md`.

## Code closed in this PR

Pure, offline-computable logic — no network and no new heavy runtime dependency.

1. **SATIM engine GIS join — offline geometric mode.**
   `tools/satim_engine/src/satim_engine/plugins/gis_join.py` performs a
   dependency-free spatial join when layer bounding boxes are supplied:
   per-point membership plus nearest-layer planar distance, emitting
   `GIS_JOIN_OFFLINE`. The geometry primitives remain in
   `plugins/gis_geometry.py`.
   - **Extension point:** swap in geopandas/rtree for polygon containment and projected/geodesic distances without changing the stable signature.

2. **SATIM engine visual OCR — typed backend extension point.**
   `tools/satim_engine/src/satim_engine/plugins/visual_ocr.py` preserves the
   deterministic filename adapter default and accepts a `VisualOcrBackend`.
   Backend errors degrade to `OCR_BACKEND_ERROR` rather than breaking the batch.
   - **External extension point:** a real OCR engine can be injected; none is fabricated or silently required.

3. **Focused offline tests.**
   GIS geometry, visual OCR backend behavior, archive safety, package builds,
   runtime smoke, and Phase-2 contracts are independently gated.

## Already code-complete and verified

- **SATIM Phase-2 calibration modules** under `fr24/calibration/`: candidate
  extraction, multi-date validation, GIS overlay, and runnable Phase-2 stage.
- **RLSM flight-track features** under `fr24/rlsm_flight_track.py` with a golden-row fixture.
- **Geo-anchor guard** that degrades cleanly when `data/rlsm/georef_anchors.csv` is absent.
- **Filename-hint `VisualOcrBackend`** as an opt-in deterministic parser.
- **Federation export** with deterministic IDs, production synthetic rejection,
  and explicit no-cueing alert guardrails.

## Remaining — offline code

1. **Real geometry backend behind `gis_geometry`.** Polygon containment and
   projected distances through the optional geospatial stack. This is an
   enhancement behind stable interfaces, not missing core logic.
2. **Incremental lint/type cleanup.** Ruff and mypy are visible in CI but remain
   report-only until the existing backlog can be reduced safely.
3. **Durable review store.** Replace the process-scoped diagnostic overlay with
   user/session-scoped persistence only when a product requirement exists.
4. **Compatibility facade retirement.** Remove root shims after a documented deprecation window.

## Remaining — data / network blocked

These gaps require external artifacts and remain typed extension points:

- **Live FR24 captures and a live production export run.** Required before
  `ready_for_hub_live_execution` can become `true`.
- **GEBCO terrain ingest** from the authoritative source stack.
- **RAG / earthgpt enrichment** if retained as an approved external extension.
- **Satellite imagery ingest** feeding the existing precomputed-detection contract.
- **ILAP intake** using locally supplied FR24 screenshots and approved OCR backends.
- **`georef_anchors.csv`** to activate the existing anchor seed path.

## Honest completion split

- **Code completeness:** the offline-computable core is substantially closed.
  Remaining code items are optional backend depth, debt reduction, and later productization.
- **Data blockage:** the residual gap to 100% is dominated by live captures,
  authoritative geospatial/imagery inputs, and production-run evidence.

---

## Completion versus maturity

This ledger measures intended code scope. `MATURITY_AUDIT.md` measures engineering
maturity and whether controls continuously protect the implementation. The numbers
therefore answer different questions.

Phase 0 now closes packaging, clean-core isolation, full-data coverage separation,
archive replacement safety, API write and identity security, immutable dependency
resolution, repository hygiene, CodeQL, secret scanning, and source-export
reproducibility. Remaining maturity work is primarily lint/type backlog reduction,
full-assets operational evidence, durable review storage, and release automation.
