# Module Spec: SATIM

## Role

Terrain and imagery context only. SATIM classifies visual/geometric artifacts
and visible scene features in screenshots and satellite/aerial imagery. It owns
image provenance, registration, image-production artifacts, terrain/landcover
observations, multi-epoch imagery tests, and bounded visual candidates. It
contains no flight-behavior or mission/purpose logic. It imports Core; it must
not import FPIM or CORRIM.

This file describes current implementation ownership. The canonical visual
reasoning decision surface is defined by
`docs/architecture/VISUAL_REASONING_CANONICAL_SPEC_v0_2.md`.

## In scope

| Path | Responsibility |
|---|---|
| `satim_calibration.py` | Core SATIM calibration engine — conservative promotion and false-positive suppression. |
| `satim_artifact_filter.py`, `satim_tile_seam_classifier.py`, `satim_render_diff.py` | Imagery artifact, seam/mosaic, rendering and image-production assessment. |
| `satim_cut_fill.py`, `satim_water_feature.py`, `satim_road_end.py`, `satim_linear_corridor.py` | Visible earthwork, surface hydrology and geometric scene-feature implementations. Canonical consumers must use only the imagery-derived portions; legacy route/ADS-B linkage outputs are noncanonical compatibility surfaces. |
| `satim_temporal_change.py`, `satim_contradiction_resolver.py`, `satim_ensemble_calibrator.py` | Multi-epoch comparison, contradiction preservation and detector-family calibration/reconciliation. |
| `satim_fit.py`, `satim_geometry.py`, `satim_ground_truth.py`, `satim_patchwork.py` | Geometry, fit, reference and patchwork imagery helpers. |
| `satim_visual_route_gap.py` | Legacy mixed visual/route surface retained for compatibility. Any track-behavior interpretation belongs to FPIM; it is not a canonical SATIM visual-reasoning input. |
| `fr24/calibration/**/*.py` | Legacy visual calibration stack. Ownership is determined per function: RLSM owns extraction/OCR primitives, SATIM owns imagery classification/artifact calibration, and FPIM owns route/flight-path interpretation. |
| `fr24/satim_engine.py`, `fr24/satim_engine_core.py` | Legacy integrated visual calibration orchestrator/runner; the filename does not make cross-domain outputs SATIM findings. |
| `src/skywatcher/satim/**/*.py` | Canonical SATIM package surfaces, including the artifact taxonomy/pipeline. |

Also SATIM-family, but excluded from the boundary AST walk because neither
imports repository implementation code (only declared standalone dependencies):

- `tools/satim_engine/` — standalone installable package, own CLI/tests.
- `tools/satim_route_findings/` — standalone read-only report generator.

## Out of scope

- Flight-path tracing, trajectory/behavior detection, route gaps as behavioral
  evidence, or POI enumeration (FPIM).
- Correlation scoring or fusing SATIM findings with FPIM output (CORRIM).
- Mission, purpose, intent, wrongdoing, target selection, access rights, or
  operational significance from imagery.
- Treating route proximity, ADS-B gaps, recurrence, or aircraft identity as
  support for a visual feature's physical identity.
- Treating low artifact likelihood as affirmative proof that a candidate is a
  true surface feature.

## Canonical visual-reasoning guardrails

The following are binding for new/refactored SATIM visual logic:

- visible anomaly != digital artifact;
- digital artifact != real-world object;
- dark region != shadow and dark region != water;
- seam != physical boundary and seam != manipulation;
- generated/inpainted/super-resolution pixels != observed evidence;
- bare ground/exposed rock != quarry;
- visual quarry != legal mine/operator identity;
- portal-like visible feature != underground-facility identity;
- text/name/proximity/nearest != exact location or identity;
- missing != zero/false/negative evidence;
- an evidentiary tie remains unresolved/review.

Numerical detector weights and confidence cutoffs embedded in legacy modules
remain candidate/calibration values unless a versioned validation artifact
promotes them. They must not be treated as universal confidence semantics.

## Legacy compatibility surfaces requiring adapters

The following existing outputs are retained for backward compatibility but are
not valid direct inputs to the canonical visual-reasoning control plane:

- `satim_cut_fill.build_p_route_confidence_patch`;
- `satim_road_end.build_p_route_confidence_patch`;
- `satim_water_feature.build_p_route_confidence_patch`;
- route/ADS-B linkage fields inside SATIM scene-feature scores;
- semantic ground-feature output from `fr24.rlsm_unlabeled`;
- any mission/intent inference surface.

Vector 2 records these as compatibility debt rather than deleting them before
callers and replay behavior are fully accounted for.

## Boundary-maintenance invariant

Every root-level `satim_*.py` implementation file must be explicitly classified
by `src/skywatcher/core/module_boundaries.py` or be listed in a named exception.
The boundary manifest is not allowed to silently lag newly added SATIM modules.
