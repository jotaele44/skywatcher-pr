# Module Spec: SATIM

## Role

Terrain and imagery context only. SATIM classifies visual/geometric artifacts in
FR24 screenshots and satellite/aerial imagery (tile seams, UI overlays, boundary
geometry, landcover/radiometric features, visible landscape morphology). It
contains no flight-behavior logic. It imports Core; it must not import FPIM or
CORRIM.

## In scope

| Path | Responsibility |
|---|---|
| `satim_calibration.py` | Core SATIM calibration engine — conservative promotion, false-positive suppression. |
| `satim_cut_fill.py`, `satim_fit.py`, `satim_geometry.py`, `satim_ground_truth.py`, `satim_patchwork.py`, `satim_render_diff.py`, `satim_road_end.py`, `satim_tile_seam_classifier.py` | Root-level imagery/geometry classifiers and calibration add-ons. |
| `src/skywatcher/satim/landscape/` | Generic landscape morphology, empirical agricultural-mosaic calibration, full competing-class vectors, benchmark gates, and provisional image-pixel field segmentation validation. This package is SATIM-only and may not consume flight behavior, route proximity, operator identity, or CORRIM findings. |
| `fr24/calibration/**/*.py` | L1-L5 SATIM calibration layers (segmenter, route-color, OCR scoring, registry audit, synthetic-boundary classifier, tile-seam-shadow calibration) and shared feature extractors. |
| `fr24/satim_engine.py`, `fr24/satim_engine_core.py` | SATIM protocol runner (`python -m fr24.satim_engine run`). |

Also SATIM-family, but excluded from the boundary AST walk because neither imports
any code from this repo (only stdlib/pandas/pyyaml):

- `tools/satim_engine/` — standalone installable package, own CLI/tests.
- `tools/satim_route_findings/` — standalone read-only report generator.

## Landscape / agricultural guardrails

- Surface appearance and land-use candidate classification are separate records.
- `COLOR_ONLY`, `CLEARING_ONLY`, and `RECTANGLE_ONLY` never promote agriculture.
- Numeric agricultural thresholds must come from a frozen empirical calibration
  profile; absent calibration fails closed rather than using a literal/default.
- Temporal recurrence is supplementary and never enters the minimum independent
  evidence count.
- Competing classes are retained in full. An unevaluated class has a `null` score,
  not zero. Tied top evidence remains `REVIEW_UNRESOLVED`.
- Field segmentation is visible image-pixel geometry. It is not cadastral parcel
  identity, crop identity, ownership, operator identity, or legal land-use identity.
- Production promotion requires both `VALIDATED` calibration and an independently
  closed benchmark with zero unexplained holdout residue.

## Out of scope

- Flight-path tracing, trajectory/behavior detection, or POI enumeration (FPIM).
- Correlation scoring or fusing SATIM findings with FPIM output (CORRIM).
- Mission, intent, wrongdoing, ownership, or legal identity inference from imagery.
- Unbounded facility-purpose inference. The separately governed v2.1 bounded
  `DUAL_USE_FUNCTION_CANDIDATE` channel remains subject to its own restrictions and
  is not expanded by the landscape classifier.

## Fixed pre-existing violations

Three SATIM files previously imported shared primitives from what became FPIM/CORRIM
territory instead of from Core (`haversine_m`, `COLOR_RANGES`/`MIN_ROUTE_PIXELS`,
`KNOWN_OPERATORS`) — see `docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md` Rationale for
the specific files and fixes.
