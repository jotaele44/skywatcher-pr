# Repository Boundary Audit — FR24 Screenshot Processing

**Date:** 2026-07-20
**Change:** Transfer FR24 screenshot-processing ownership SpiderWeb → Skywatcher.
**Scope:** code-only (no screenshots processed, no operational DB created, no data moved).

## Boundary decision

| Capability | Owner (after) |
|---|---|
| FR24 screenshot source / ingestion | **skywatcher-pr** |
| FR24 OCR + telemetry parsing + normalization | **skywatcher-pr** |
| Screenshot→flight reconstruction, track points | **skywatcher-pr** |
| Validation / confidence / review-status | **skywatcher-pr** |
| FR24 database schema + init/migrations | **skywatcher-pr** |
| Canonical export + bridge serialization | **skywatcher-pr** |
| Downstream correlation (GIS / mission / operational / anomaly) | **spiderweb-pr** (retained) |
| Validated-export consumer (`--ingest-skywatcher`) | **spiderweb-pr** (retained bridge) |

Skywatcher consolidated the pipeline into the src-layout package
`src/skywatcher/fr24/` (wrapping the existing tested `fr24/*` modules). SpiderWeb
removed the active FR24 screenshot code and retains only downstream intelligence
plus a schema-validated hub-canonical consumer.

## Contradiction review (Phase 10)

| ID | Contradiction | Resolution |
|---|---|---|
| C1 | Mission classification: forbidden in Skywatcher (ADR) vs. a bridge field | ADR revised: mission inference permitted but **gated** (`highly_speculative` until evidence > 0.85 → `evidence_gated`). Bridge field OPTIONAL, never a Skywatcher-confirmed fact. `src/skywatcher/fr24/mission_classification.py`. |
| C2 | `confirmed` is prohibited in the bridge but a valid enum value in spatial schemas | Bridge keeps the prohibited-terminal-label gate (both producer + consumer). Spatial `identity_status='confirmed'` etc. live in a different namespace and are untouched; the bridge review vocabulary excludes `confirmed`. |
| C3 | Confidence: flat float (Skywatcher) vs. object `{score,method}` (Spiderweb) | Bridge `confidence` is an object `{score:0..1, method}`. `spiderweb_export.build_bridge_record` wraps Skywatcher's float. |
| C4 | Disjoint `review_status` vocabularies | Explicit crosswalk in `src/skywatcher/fr24/review_status.py` (`draft→unreviewed`, `needs_review/reviewed→reviewing`, `promoted→approved`, `rejected→rejected`; unknown→`unreviewed` fail-safe). Bridge emits the Spiderweb vocabulary. |
| C5 | `coordinate_method` closed enum (Spiderweb) rejects Skywatcher values | Widened enum used in the DB schema and bridge: `fixed_pr_bounds, airport_anchor, manual_anchor_csv, per_screenshot_affine, synthetic_wgs84_point, unknown`. |
| C6 | Ownership documented but not enforced (SpiderWeb still had FR24 code) | Resolved by this change: active FR24 code removed from SpiderWeb (see zero-hit audit). |
| C7 | Timestamp naming (`created_at` vs `generated_at`) | Bridge canonicalizes on `generated_at_utc`. |

## Unresolved / deferred (recorded, not invented)

- **FR24 record schema JSON files in spiderweb-pr** (`screenshot.schema.json`,
  `ocr_raw_by_zone`, `ocr_normalized_labels`, `extracted_field`,
  `aircraft_observations`, `flight_track_features`) were **retained as inert data
  contracts**. Physical deletion cascades into `schemas/schema_index.json`
  (400+ entries), `tests/test_schema_validation.py`, and CI; `schema_validation`
  already skips absent tables gracefully. The active *code* is removed (zero-hit
  passes). Recommended follow-up: prune these schemas + index entries in a
  dedicated cleanup PR.
- **Downstream flights source in SpiderWeb**: phases 2-4 now depend on the
  bridge (`--ingest-skywatcher`) to populate `flights`/`track_points`. If no
  Skywatcher package is ingested, those tables are empty (as they would be with
  an empty DB previously). No behavioral regression, but operationally the
  federation live-export path (`ready_for_hub_live_execution=false` in
  skywatcher) must be enabled before end-to-end runs are meaningful.
