# Module Spec: SATIM

## Role

Terrain and imagery context only. SATIM classifies visual/geometric
artifacts in FR24 screenshots and satellite/aerial imagery (tile seams, UI
overlays, boundary geometry, landcover/radiometric features). It contains no
flight-behavior logic. It imports Core; it must not import FPIM or CORRIM.

## In scope

| Path | Responsibility |
|---|---|
| `satim_calibration.py` | Core SATIM calibration engine — conservative promotion, false-positive suppression. |
| `satim_cut_fill.py`, `satim_fit.py`, `satim_geometry.py`, `satim_ground_truth.py`, `satim_patchwork.py`, `satim_render_diff.py`, `satim_road_end.py`, `satim_tile_seam_classifier.py` | Root-level imagery/geometry classifiers and calibration add-ons. |
| `fr24/calibration/**/*.py` | L1-L5 SATIM calibration layers (segmenter, route-color, OCR scoring, registry audit, synthetic-boundary classifier, tile-seam-shadow calibration) and shared feature extractors. |
| `fr24/satim_engine.py`, `fr24/satim_engine_core.py` | SATIM protocol runner (`python -m fr24.satim_engine run`). |

Also SATIM-family, but excluded from the boundary AST walk because neither
imports any code from this repo (only stdlib/pandas/pyyaml):

- `tools/satim_engine/` — standalone installable package, own CLI/tests.
- `tools/satim_route_findings/` — standalone read-only report generator.

## Out of scope

- Flight-path tracing, trajectory/behavior detection, or POI enumeration
  (FPIM).
- Correlation scoring or fusing SATIM findings with FPIM output (CORRIM).
- Facility-purpose or intent inference from imagery alone (explicitly
  forbidden per `docs/SKYWATCHER_SATIM_PIPELINE_SPEC.md`'s existing
  "do not infer facility purpose from screenshots/images alone" rule — SATIM
  classifies objective observation classes like `TILE_SEAM`, `UI_OVERLAY`,
  `ZOOM_BLUR`, never intent classes).

## Fixed pre-existing violations

Three SATIM files previously imported shared primitives from what became
FPIM/CORRIM territory instead of from Core (`haversine_m`,
`COLOR_RANGES`/`MIN_ROUTE_PIXELS`, `KNOWN_OPERATORS`) — see
`docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md` Rationale for the specific files
and fixes.
