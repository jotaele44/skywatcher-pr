# RLSM extraction — operator runbook

**One command.** Everything else in this file is context for when something goes wrong.

```bash
cd ~/Documents/GitHub/skywatcher-pr
./run-rlsm.sh
```

That runs the whole chain — inventory → OCR → aircraft → labels → icons → geocode →
review queue → exports → report — resumably, with a preflight that fails fast and a
written summary at the end. Ctrl-C and re-run is always safe.

**Why it runs here and not in the cloud:** OCR over ~13.3k images is hours of wall time
and the corpus is machine-local. Everything downstream of the sqlite (labels, review,
exports, reports) needs no images and runs anywhere — see "Split the work" below.

## Before the first run

### 1. Point `data/FR24_baseline` at the corpus

Paths in the database are stored relative to the repo root, so the corpus must be
reachable at exactly `data/FR24_baseline`. A symlink is fine:

```bash
ln -s ~/Documents/GitHub/spiderweb-pr/data/FR24_baseline data/FR24_baseline
```

Preflight prints this command for you if the directory is missing.

### 2. Install the toolchain

```bash
brew install tesseract
pip install -r requirements.txt
pip install pytesseract
```

`pillow-heif` (in requirements.txt) is what makes `.heic` screenshots readable; without
it they are recorded as unreadable rather than silently skipped.

### 3. Check the plan without touching anything

```bash
./run-rlsm.sh --dry-run     # stage plan + full preflight, no writes
./run-rlsm.sh --limit 200   # smoke test the whole chain over 200 images
```

## Timing

At `--workers 4` on Apple Silicon, over ~13.3k images:

| Stage | Cost | Notes |
|---|---|---|
| inventory | minutes | sha256 + phash; skips anything already ingested |
| ocr | ~2 h | 3 zones per image; the dominant cost |
| aircraft | seconds | regex over stored text |
| pins | seconds | gazetteer match over stored word boxes |
| icons | ~1–1.5 h | one extra RGB decode per screenshot |
| geocode / review / export / report | seconds–minutes | |

**~3–3.5 h total.** Drop the icon pass with `--skip-icons` for ~2 h. Intel Macs, multiply
by roughly 1.5.

If your database was OCR'd by an earlier version, preflight will report a
`screenshots_needing_word_boxes` count and the OCR stage will re-read those images to
recover per-word geometry (roughly another 2 h). This is a one-time backfill: existing raw
OCR is never overwritten, new rows are appended under a fresh `run_id`.

## Common flags

```bash
./run-rlsm.sh --status            # what is done, what is pending (JSON)
./run-rlsm.sh --workers 2         # be gentler on a busy machine
./run-rlsm.sh --from icons        # resume from a stage after a failure
./run-rlsm.sh --stage pins        # re-run exactly one stage
./run-rlsm.sh --skip-icons        # OCR + labels + exports only
./run-rlsm.sh --stage unlabeled   # the ground-feature blob pass (see below)
```

`unlabeled` is **not** in the default run. It emits ~40–50 candidates per image
(~500k rows) using a satellite-imagery taxonomy — `pad`, `tank`, `quarry` — aimed at
ground features rather than app chrome, and it would swamp the review queue. The icon
channel is the better-typed signal for on-screen glyphs. Run it deliberately if you want it.

## The one manual step: naming icon classes

The icon stage detects glyphs and clusters them by perceptual hash. Because UI glyphs are
pixel-identical between renders, the whole corpus collapses to a few dozen classes. Name
each class once and every recurrence inherits it:

```bash
# 1. the icons stage already wrote this file
open data/reference/icon_classes.json

# 2. fill in "icon_class" per cluster — the file lists each cluster's colour,
#    size, and the labels it most often sits beside
#    suggested vocabulary: airport, heliport, aircraft, navaid, city_dot, seaport,
#    ui_chrome, noise

# 3. apply
python3 scripts/rlsm_icon_cluster.py --apply
```

That is ~30 decisions covering every icon in the corpus. Once applied, the run report
gains an icon-class-vs-label-type agreement table: an airport glyph beside a garbled
string that matched a municipio is a contradiction worth flagging; the same glyph beside
`TJSJ` is confirmation.

## What you have at the end

Read `outputs/rlsm_run_report.md` first — it carries the numbers that matter.

- **`screenshots`** — one row per image, with `ocr_status`
- **`ocr_observations`** — raw text *and* per-word pixel boxes (`raw_lines_json`), immutable
- **`aircraft_observations`** — registration / type / altitude / speed per frame
- **`labeled_pins`** — every matched place name **with real pixel geometry**, matched
  against the 5,744-key GNIS gazetteer (`data/reference/Gazetteer_PR_GNIS.gpkg`)
- **`icon_observations`** — map glyphs keyed to their pin, with colour, shape and hash
- **`manual_review_queue`** — genuinely uncertain items only
- 14 CSV/JSONL exports plus the coverage report in `outputs/`

The report metric to watch is **screenshots with ≥2 located pins**: that is the population
the per-screenshot affine geocoder can fit, which is what turns approximate frames into
`located` observations (docs/SCREENSHOT_DATA_STRATEGY.md §1).

## Split the work

Only `inventory`, `ocr`, `icons` and `unlabeled` decode images and need the corpus.
Everything else runs off the sqlite alone — preflight knows this and will not demand
tesseract or the corpus for a DB-only stage. So:

```bash
# on the Mac, where the images are
./run-rlsm.sh --stage ocr

# anywhere, with just the sqlite
./run-rlsm.sh --from pins
```

Ship the small sqlite-derived reports, never the corpus.

## Resume and rollback

- Every stage is idempotent. Re-running does not double-emit.
- To force a re-OCR after a config change, reset the status on the rows you want redone:
  ```sql
  UPDATE screenshots SET ocr_status='pending' WHERE month_bucket='2025-08';
  ```
- Raw OCR is **never** overwritten. Re-runs append under a new `run_id`, and the extractors
  read the newest observation per zone — so rows from the legacy 6-zone run, the 3-zone run
  and any word-box backfill coexist without double-counting.
- The label extractor rebuilds `labeled_pins` from scratch each run (`--reset-labeled-pins`),
  so gazetteer or confidence changes take effect on the next `./run-rlsm.sh --stage pins`
  without touching OCR.

## Verifying the extraction itself

```bash
python3 -m pytest tests/test_rlsm_label_extraction.py -q   # accuracy: 46 tests, no corpus needed
python3 -m pytest tests/test_rlsm_pipeline.py -q           # structural invariants
python3 -m fr24.rlsm_gazetteer --stats                     # gazetteer size and tiering
python3 -m fr24.rlsm_gazetteer --lookup "MAYAGÜEZ"         # resolve a single label
```
