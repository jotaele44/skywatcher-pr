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

The geocode stage does not require `data/places.geojson`. Clean clones use the
tracked GNIS GeoPackage at `data/reference/Gazetteer_PR_GNIS.gpkg` plus any
existing `geo_anchors` rows, and preflight verifies that coordinate lookup before
the expensive image-decoding stages run.

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

## Source availability versus ingestion status

`ingest_status` is historical: it records whether a source was readable when
it entered RLSM and is never rewritten merely because the file was moved,
archived, or lost. `source_availability` records the current source state:

- `present` — reachable at `rel_path`;
- `missing_on_disk` — absent or SHA-invalid;
- `restored` — recovered and verified against the stored SHA-256;
- `archived` — intentionally stored elsewhere with a controlled locator.

Dry-run remains read-only and writes only reports. Apply is one fail-closed
operation: it re-plans under `BEGIN IMMEDIATE`, compares the locked database
snapshot and plan digest to the preliminary plan, creates a no-overwrite
verified snapshot backup, and only then performs file and database actions.

```bash
python3 scripts/rlsm_reconcile_source_availability.py \
  --db /path/to/rlsm.sqlite \
  --repo-root /path/to/skywatcher-pr \
  --verify-sha \
  --output-dir /path/to/reconciliation-report
```

Apply requires a backup destination that does not exist:

```bash
python3 scripts/rlsm_reconcile_source_availability.py \
  --db /path/to/rlsm.sqlite \
  --repo-root /path/to/skywatcher-pr \
  --verify-sha \
  --apply \
  --backup /path/to/rlsm.pre-source-availability.sqlite \
  --output-dir /path/to/reconciliation-report
```

The backup is created while the write reservation is held and is verified by
SQLite integrity check, every user-table name and row count, schema hashes,
foreign-key state, and SHA-256. A failed verification removes only the backup
inode created by that run.

A restore manifest is CSV or JSON with `rel_path`, `source_path`, and optional
`sha256`. Every manifest `rel_path` must identify exactly one screenshots row.
Unknown, duplicate, unsafe, or ambiguous entries fail closed. Candidate and
existing-path hashes are revalidated immediately before copying.

Exact restorations are prepared beside the destination and installed with an
atomic no-overwrite hard link. Newly restored files are recorded in a
compensation ledger. If the SQLite transaction fails before commit, RLSM rolls
back the database and removes only restored files whose inode and SHA-256 still
match the receipt. Quarantine copies are non-destructive evidence and remain
available after a failed apply.

Serial and parallel OCR fail closed on an unmigrated database and select only
`present` or `restored` sources. A file disappearing after selection becomes
`missing_on_disk`; its `ocr_status` remains pending and is accounted separately
from OCR-engine failures.


### Atomicity review v0.21

The mutating reconciler preserves caller-owned file-action and compensation
ledgers so an exception during any later action still removes every earlier
restored file. All planned filesystem states are revalidated after backup and
immediately before commit. Restore-manifest entries targeting already-present
sources are rejected as unused. Verified backups compare deterministic content
hashes for every user table, not only schemas and row counts.


## Control-path namespace isolation

Application control artifacts must never occupy, contain, or sit beneath an
expected source path, restore candidate, SQLite database/sidecar, or quarantine
namespace. The reconciler rejects overlapping backup and quarantine paths before
creating a backup. Report output is also rejected when writing it would turn an
evidence file into a directory or collide with the database or backup file.

This matters even for a failed apply: a valid backup is intentionally retained
after later failures, so its destination must be proven disjoint from the corpus
before any backup byte is installed.


## Apply-artifact durability and report namespace safety

The verified backup, every restored source, and every quarantine copy are
revalidated by inode, SHA-256, and recorded size immediately before the SQLite
commit. If any artifact disappears or is replaced, the database transaction
rolls back and newly restored files are compensated.

Fixed report filenames are treated as control paths, not only the report output
directory. They may not equal, contain, or sit beneath an expected source,
restore candidate, backup, quarantine directory, database/sidecar, or restore
manifest. This prevents a successful apply followed by a report-write failure
and prevents reports from occupying future evidence paths.

The report output root may contain disjoint operational subtrees, including the
default `quarantine/` directory. Isolation is enforced directionally: the output
root may be an ancestor, but the concrete `runs/`, `dry-runs/`, generation
directory, and report files must remain disjoint from every protected artifact.


## External corpus links and terminal path checks

The reconciler preserves repository-relative operational source paths so the
documented `data/FR24_baseline` symlink may target a corpus outside the Git
worktree. It still rejects lexical `..` traversal and fails closed when multiple
database rows use the same `rel_path` or resolve to the same source target.

Quarantine evidence must be an independent inode, not a hard link to the
mismatched source. Report output is probed before apply; non-directory output
ancestors, directory-valued report destinations, and report symlinks are
rejected before any database transaction can commit.

If a selected OCR source disappears between the eligibility check and image
open, both serial and parallel runners record `missing_during_ocr`, preserve
`ocr_status='pending'`, and account the row separately from OCR-engine failures.


## Final candidate v1.0 — authoritative state machine

This section supersedes the incremental repair notes above. The authoritative
implementation is protocol `rlsm-source-availability-v1.0` and treats database,
source files, backup, quarantine evidence, and reports as one coordinated
operation.

The successful path is:

1. acquire `BEGIN IMMEDIATE` and bind the complete logical database snapshot;
2. rebind the optional restore manifest and produce the final deterministic plan;
3. validate every control/evidence namespace;
4. create and content-verify an immutable backup;
5. copy bound source descriptors, install restorations without overwrite, and
   create independent quarantine evidence;
6. revalidate every planned source and created artifact;
7. prepare schema migration, row updates, and an in-progress processing run;
8. publish immutable generation-scoped reports and a `commit_prepared` receipt;
9. store the authoritative `committed` receipt in the processing run;
10. revalidate backup, sources, quarantine, and reports immediately before commit;
11. commit, or resolve an exceptional commit return by reading the authoritative
    completed processing-run receipt.

The file named `terminal_apply_receipt.json` deliberately has state
`commit_prepared`. It is not allowed to claim that SQLite committed before the
commit occurs. Commit authority is the matching `processing_runs` row with
`status='completed'`, the same plan digest, and a valid receipt SHA-256.

All failures before a verified commit roll back SQLite and emit a structured
failure receipt on the raised `ReconciliationError`. Newly restored files and
report artifacts are removed only when both inode and SHA-256 still match the
attempt receipt. Backups and quarantine copies are retained as evidence.
Non-empty attempt-created directories are retained rather than deleting foreign
content that appeared concurrently.

The documented external `data/FR24_baseline` directory symlink is supported.
Repository-relative operational paths remain lexical and safe, while file actions
use descriptor-bound sources and resolved destinations. A corpus retarget before,
during, or immediately after restore installation blocks the operation and
compensates the resolved file and temporary artifacts.

Restore manifests are read through a stable descriptor and bound by path,
resolved path, inode, size, timestamps, SHA-256, entry count, and canonical entry
digest. A changed or replaced manifest is rejected before backup creation.

Dry-run reports are immutable and content-addressed under
`<output>/dry-runs/dry-run-<digest>/`. Repeating an identical dry run returns the
same verified files; altered existing bytes fail closed. Apply reports are
immutable under `<output>/runs/<run_id>-<plan_digest>/` and are fully prepared
before database commit.

OCR opens source files through a stable descriptor. Missing, unlinked, retargeted,
or replaced sources are recorded as `missing_during_ocr`, and `ocr_status` is
reset to `pending` even when the row was selected through retry-failed mode.
No OCR observations are deleted or overwritten.


## Terminal candidate v2.0 — deterministic public dry runs

Content-addressed dry-run transition reports deliberately omit the volatile
`checked_at` invocation timestamp. Plan identity, paths, hashes, bindings,
actions, and database snapshot evidence remain included. This makes repeated
public dry runs over unchanged inputs byte-identical and safely idempotent.
Apply reports retain the operation timestamp because each apply has a unique
processing run and immutable generation directory.
