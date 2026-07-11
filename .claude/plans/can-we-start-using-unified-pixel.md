# Wire the SATIM engine (L1–L5) to currently available process + raw data

## Context

Two questions were asked:

1. **"How many flights from N440TT are in the processed logs?"** → **Zero.** `N440TT`
   appears nowhere: not in the 10,614 OCR sightings (`outputs/ocr_events/full_sightings.jsonl`,
   309 distinct tails), not in `events.csv`, `confirmed_new_tails.json`, either fleet roster,
   or anywhere in the repo (case-insensitive sweep; `N440*` has no near-miss either).
   The corpus is OCR-derived with documented misreads, so "0" means *not detected in the
   processed screenshots*, not provably never-present. Likely a wrong tail or one to add.

2. **"Can we start using the SATIM engine on current data?"** → Partially today; the rest is a
   **wiring gap, not a data gap.** The label-scoring engine (`satim_calibration.py`) already ran
   (`exports/satim_calibration/SATIM-CAL-MOCA-C6038_v1/`). The L1–L5 calibration *modules* all
   exist (`fr24/calibration/`), and the raw data exists (`data/FR24_baseline/**` = 10,614 PNGs,
   `outputs/ocr_events/` OCR corpus, `data/ground_truth/` track corpus) — but the documented
   commands point at example paths that don't exist (`data/fr24/screenshots`, etc.). The modules
   take real `--input`/`--*-csv` args, so they can be pointed at the existing data via small
   format-shim scripts.

**Goal (user chose Full L1–L5 wiring):** build the shims that feed each layer from existing data,
run the full pipeline, and produce a real `reports/satim/calibration_report.json` consumable by
the PRII readiness engine via `fr24/calibration/readiness_adapter.py`.

## Current per-layer state (verified)

| Layer | Module input contract | Source on disk | Shim needed |
|---|---|---|---|
| **L1** segmenter | `--input <dir>` → `rglob` images | `data/FR24_baseline/**` | None — point at it |
| **L2** route | `--input <dir>` (+ optional `--blank-input`) | `data/FR24_baseline/**` | Optional blank-tile sample |
| **L3** OCR scoring | `--ground-truth CSV` (image_path + fields) + `--predictions JSON` | predictions: `full_sightings.jsonl`; truth: `data/ground_truth/**` track CSVs | **Two builders** (heaviest) |
| **L4** registry audit | `--fr24-csv` with `registration`/`callsign`/`operator`/`aircraft_type` | `outputs/ocr_events/events.csv` (col `tail`) | Column-map CSV |
| **L5** tile-seam | `--candidates-csv` with feature scores | none (satellite/aerial domain) | **Must produce candidates** |

Readiness rule (`fr24/calibration/models.py`): base layers `L1/L2/L3` must all be `READY` or
overall is `DEGRADED`; `L4`/`L5` not `READY` → `PARTIAL`; all five `READY` →
`READY_FOR_BATCH_ANALYSIS`.

## Approach

Create shim/builder scripts under `scripts/` (matching existing `scripts/fr24_*.py` /
`satim_*` naming), write derived inputs under `data/fr24/**` and `reports/fr24/**`, then run the
existing layer modules unchanged. Do **not** invent data — only reshape what exists.

### 1. L1 — run directly (no new code)
`python -m fr24.calibration.l1_segmenter_calibration --input data/FR24_baseline --output reports/satim/l1_segmenter_report.json`
Requires Pillow (already implied by L2). Status is empirical; inspect `route_pixel_coverage` /
`panel_text_overlap`.

### 2. L2 — run directly; optionally stage blank tiles
`--blank-input` is optional (no blanks ⇒ FPR 0.0, blocker can't fire). For a real FPR measurement,
stage a small `data/fr24/blank_tiles/` from ocean/blank baseline screenshots (a selector script or
manual copy). Then run `l2_route_calibration`.

### 3. L3 — two builder scripts (critical path)
- **`scripts/satim_build_l3_predictions.py`**: read `outputs/ocr_events/full_sightings.jsonl`,
  emit `reports/fr24/vision_ingest_output.json` as a list keyed by `image_path` (= sighting `path`),
  mapping `tail→callsign`, `alt_ft→altitude_ft`, `type_guess→aircraft_type`, `airport_codes→
  origin_code/destination_code`. (L3's `load_predictions` accepts a list of `{image_path,...}`.)
- **`scripts/satim_build_l3_ground_truth.py`**: the ground-truth corpus (`data/ground_truth/<tail>/
  *.csv`) is FR24 **track points** (`Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction`),
  keyed by time, not screenshot. Build `data/fr24/ground_truth/satim_l3_ground_truth.csv` with one
  row per screenshot, joining each sighting's `ts_utc` to the nearest track-point by timestamp →
  populate `image_path`, `callsign`, `altitude_ft`. Leave `aircraft_type`/`origin_code`/
  `destination_code`/`nearest_location` blank — **L3 skips blank truth fields**, so a 2-field
  ground truth is valid and scores `callsign`/`altitude_ft` only.
- Run `l3_ocr_scoring`. Note: `READY` needs field scores ≥0.90 — an *accuracy* gate. Wiring makes
  L3 runnable and measurable; `PARTIAL`/`DEGRADED` is an honest possible result, not a failure of
  the plan.

### 4. L4 — one column-map script
**`scripts/satim_build_l4_export.py`**: `outputs/ocr_events/events.csv` → `data/fr24/exports/
fr24_export.csv`, mapping `tail→registration`, `registry_owner→operator`, `registry_type→
aircraft_type` (keep `tail` as `tail_number`). Then run `l4_registry_audit`. Coverage threshold is
≥50%; `events.csv` carries `in_known_fleet`/`registry_status`, so L4 should reach `READY`.

### 5. L5 — produce candidates (honest constraint)
L5 scores satellite/aerial artifact features (`straight_boundary_score`,
`radiometric_discontinuity_score`, `cloud_mask_intersection`, … `infrastructure_alignment`). **No
such candidates exist in the corpus today.** `l5_synthetic_boundary_classifier.py` consumes the
same candidate CSV; neither produces it from raw imagery. Two honest paths:
- **(a)** Build `scripts/satim_build_l5_candidates.py` to stage a *real* candidates CSV from any
  marked satellite/aerial features (e.g. derived from `data/satim_calibration/**` marked labels) —
  L5 reports `READY` with ≥1 genuine row.
- **(b)** If no genuine satellite candidates can be sourced, L5 stays `MISSING` and overall caps at
  `PARTIAL`. **This is the expected ceiling** unless real L5 input is created/marked. Surface this
  explicitly rather than fabricating candidate rows.

### 6. Aggregate + PRII handoff (no new code)
`python -m fr24.calibration.run_satim_calibration --l1 … --l5 … --output reports/satim/calibration_report.json`,
then feed `fr24/calibration/readiness_adapter.py` into the PRII engine (`prii_readiness_engine.py`).
Optionally add `scripts/run_satim_pipeline.sh` orchestrating builders → layers → merge.

## Files to create / modify

- **New** `scripts/satim_build_l3_predictions.py` — JSONL→predictions JSON
- **New** `scripts/satim_build_l3_ground_truth.py` — timestamp-join sightings↔track CSVs
- **New** `scripts/satim_build_l4_export.py` — events.csv column map
- **New** `scripts/satim_build_l5_candidates.py` — stage L5 candidates (path (a)); else document gap
- **New (optional)** `scripts/run_satim_pipeline.sh` — orchestrator
- **New (generated, gitignore-as-appropriate)** `data/fr24/ground_truth/satim_l3_ground_truth.csv`,
  `data/fr24/exports/fr24_export.csv`, `data/fr24/blank_tiles/`, `reports/fr24/vision_ingest_output.json`,
  `reports/satim/l{1..5}_*.json`, `reports/satim/calibration_report.json`
- **No edits** to `fr24/calibration/*` modules — they already accept the needed args.

## Verification

1. Run each builder, then each layer module; confirm each `reports/satim/lN_*.json` has a valid
   `status` and non-empty `metrics` (e.g. L1 `image_count` ≈ 10,614).
2. Run `run_satim_calibration`; inspect `reports/satim/calibration_report.json` `overall_status`.
   Expected realistic outcome: `PARTIAL` (L1/L2/L4 likely `READY`; L3 accuracy-gated; L5 likely
   `MISSING` without real candidates). `READY_FOR_BATCH_ANALYSIS` only if L3 passes thresholds and
   L5 has genuine candidates.
3. `python -m pytest tests/test_satim_calibration.py -q` (and any `tests/test_satim*`/L-layer tests)
   to confirm no regressions.
4. Run `readiness_adapter` → confirm PRII engine reads the report without the "missing
   calibration_report.json" degraded warning.
