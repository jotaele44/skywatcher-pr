# RLSM extraction — local-machine handoff

**Purpose:** This document tells you how to finish the long-running phases (OCR + unlabeled vision pass) on your Mac instead of through Claude's sandbox, then come back here for the cheap derived-extraction phases.

**Why the split:** OCR over 11,901 images at ~2.8 s/image is ~9 hours single-threaded. With 4 parallel workers it drops to **~2 hours** locally. Running it through Claude would burn ~1,983 bash calls and ~20 hours of wall time. The runner is built; just point it at the data on your Mac.

## What's already done (in DB and ready)

- `data/rlsm/rlsm_screenshot_analysis.sqlite` — 9-table schema, 11,926 screenshots ingested, 1 missing-on-disk row flagged, 1 corrupt row flagged. Inventory is **100% complete**.
- `outputs/rlsm_ingest_manifest.csv` (11,926 rows), `rlsm_duplicate_report.csv`, `rlsm_failed_files.csv`.
- Zone schema **calibrated for iPhone portrait FR24** (3 zones: status_bar, label_layer, aircraft_card) — verified 2.758 s/image in sandbox.
- Resumable runners: `fr24.rlsm_ocr` (serial), `fr24.rlsm_ocr_parallel` (multi-worker), `fr24.rlsm_unlabeled` (visual pass), `fr24.rlsm_extractors` (aircraft + POI + review queue), `fr24.rlsm_export`, `fr24.rlsm_coverage`.
- Tests: `tests/test_rlsm_pipeline.py` — 10/10 passing.

## Run these on your Mac, in order

```bash
cd ~/Documents/GitHub/spiderweb-pr

# 1) Parallel OCR — ~2 hours wall time @ 4 workers (Apple Silicon M1+)
#    Resumable; safe to Ctrl-C and re-run. Each worker uses its own SQLite conn (WAL handles it).
OMP_THREAD_LIMIT=1 python3 -m fr24.rlsm_ocr_parallel --workers 4 --budget-sec 86400

#    Optional: try a smaller workers count first if your machine is busy
#    OMP_THREAD_LIMIT=1 python3 -m fr24.rlsm_ocr_parallel --workers 2 --budget-sec 86400

# 2) Unlabeled POI vision pass — ~80 min wall time single-threaded
#    Already at ~0.4 s/image; the cost is the connected-component CC labeling, not OCR.
python3 -m fr24.rlsm_unlabeled --budget-sec 86400

# 3) Derived extractors — seconds, runs against the OCR results
python3 -m fr24.rlsm_extractors --kind all

# 4) Re-export the 14 CSVs/JSONL and regenerate coverage report
python3 -m fr24.rlsm_export
python3 -m fr24.rlsm_coverage

# 5) Verify the structural invariants
python3 -m pytest tests/test_rlsm_pipeline.py -q
```

Then come back here. I'll pick up from the populated DB for any downstream analysis you want.

## ETAs (calibrated)

| Phase | Per-image | Total (4 workers) | Total (single thread) |
|---|---|---|---|
| OCR (3 zones, AMD oem 1 LSTM) | 0.7 s | **~2 h 20 m** | ~9 h |
| Unlabeled vision pass | 0.4 s | n/a (single proc) | **~80 m** |
| Extractors | <10 ms | seconds | seconds |
| Exports + coverage | n/a | seconds | seconds |

Apple Silicon (M1/M2/M3) is typically 1.5–2× faster than the sandbox VM, so expect lower than these numbers. If you have an Intel Mac, multiply by ~1.5.

## Progress monitoring while it runs

The parallel runner prints a progress line every 50 images with rate and remaining ETA. Alternatively, in a second terminal:

```bash
watch -n 5 'sqlite3 ~/Documents/GitHub/spiderweb-pr/data/rlsm/rlsm_screenshot_analysis.sqlite \
  "SELECT ocr_status, COUNT(*) FROM screenshots GROUP BY ocr_status"'
```

## What you'll have at the end

- **`screenshots`** (11,926 rows) with `ocr_status='ok'` on every present-on-disk file
- **`ocr_observations`** — ~35,772 rows (3 zones × 11,924 ok files), raw text immutable
- **`aircraft_observations`** — one row per screenshot where we extracted a registration / type / altitude / speed
- **`labeled_pins`** — every map label found (dedup'd per screenshot)
- **`unlabeled_pin_candidates`** — visual features without labels, ~40-50 per image average → ~500,000 candidates total. All flagged unreviewed.
- **`manual_review_queue`** — auto-derived review items spanning all 5 spec categories

## Resume / rollback

- All runners are idempotent. Re-running won't double-emit.
- To re-run OCR after a config change, set `ocr_status='pending'` on the rows you want re-done:
  ```sql
  UPDATE screenshots SET ocr_status='pending' WHERE month_bucket='2025-08';
  ```
- The old `ocr_observations` rows from prior runs are kept; new rows are written with a fresh `run_id`. Raw OCR is **never** overwritten.
- The 138 `ocr_observations` rows currently in the DB are from the prior 6-zone run; they're valid raw data and will sit alongside the new 3-zone rows.

## Tier-1 changes in this session (why per-image cost dropped from 5.8 s → 2.8 s)

- **Dropped** `top_bar` zone: only contains the static "flightradar24" wordmark — 0 information per image.
- **Dropped** `bottom_actions` zone: only contains "Route Follow More info" button labels — 0 information.
- **Merged** `label_layer` and `map_center` into one wider crop with a single OCR call (was two crops with identical content).
- Net: 6 zones → 3 zones, **50% reduction in tesseract invocations per image**.

## Tier-4 future tuning (not applied yet — apply only if accuracy gaps appear)

After the bulk OCR run, if specific zones show low recall:

1. **Custom user_patterns** for tesseract (FAA N-numbers, altitude, mph patterns) — `--user-patterns ~/.config/rlsm/patterns.txt`
2. **Color-keyed preprocessing for label_layer** — isolate white text on map before OCR (HSV mask + morphological close)
3. **PSM 4 retry for low-conf aircraft_card** — second pass with single-column-of-text layout assumption

These are all noted in the manual review queue; you can tackle them per-zone after seeing the bulk results.

## Cost summary

| Item | Sandbox-only baseline | Local-handoff optimized |
|---|---|---|
| Wall time for full OCR | 13–20 h | **~2 h** |
| Claude bash calls for OCR | ~1,983 | **0** |
| Total Claude session calls (all phases) | ~2,100 | **~6** |
| Per-image OCR cost | 5.8 s | 0.7 s (parallel) |

The economy lever isn't tesseract — it's **moving the long-running compute off Claude entirely** and using your local machine for what local machines are for.
