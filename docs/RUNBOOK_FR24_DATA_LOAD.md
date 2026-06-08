# Runbook: FR24 Data Load (manifest audit → OCR/DB build → calibration)

This runbook covers the three data-gated steps that turn the raw FlightRadar24
screenshot corpus into a calibrated operational database:

1. **FR24 manifest audit** — pre-ingest gate over the raw corpus
2. **OCR / operational-DB build** — populate the flight database
3. **Spiderweb operational calibration** — validate scoring against the real DB

These steps require the full screenshot corpus (~15k images) on local disk and
must run on the machine that holds it — not in an ephemeral cloud session.
Steps run in order; each has a gate that must pass before the next.

> `fr24/manifest_audit.py` uses `datetime.UTC` and **requires Python 3.11+**.
> The corpus location is passed explicitly via `--root`; do not rely on any
> path baked into the source.

## Part 0 — Environment setup

```bash
git clone https://github.com/jotaele44/spiderweb-pr.git
cd spiderweb-pr

python3 -m pip install -r requirements-airspace.txt   # includes pillow-heif for .heic
brew install tesseract                                 # macOS; Ubuntu: apt-get install tesseract-ocr
```

Set the corpus root. The corpus lives under the repo's `data/` directory,
which is gitignored (`data/*` in `.gitignore`) — so the raw images are never
git-tracked and the audit's `git_tracked_raw_files` gate passes by
construction. Run all commands below from the repo root:

```bash
CORPUS="data/Flight Logs"
# absolute equivalent: /Users/jotaele/Documents/GitHub/spiderweb-pr/data/Flight Logs
```

## Part 1 — FR24 manifest audit (read-only)

```bash
# 1a. Discover the FR24 shard layout under the corpus root
python fr24/manifest_audit.py --root "$CORPUS" --discover-fr24-folders

# 1b. Fast smoke audit (first 50 images) to confirm the path resolves
python fr24/manifest_audit.py --root "$CORPUS" --output-dir /tmp/fr24_audit --max-images 50

# 1c. Full audit — add --combined if 1a listed more than one */Google Photos/FR24 folder
python fr24/manifest_audit.py --root "$CORPUS" --output-dir /tmp/fr24_audit
```

**Gate:** `/tmp/fr24_audit/fr24_manifest_audit_report.json` must report
`audit_pass == true` (`corrupt == 0`, `db_files_in_tree == []`,
`git_tracked_raw_files == []`). On failure, apply the remediation table in
[`FR24_MANIFEST_AUDIT.md`](FR24_MANIFEST_AUDIT.md) — quarantine corrupt images,
move stray `.db` files out of the tree, untrack any git-tracked raw files —
then re-run 1c. Do not start Part 2 until the audit passes.

## Part 2 — OCR / operational-DB build

Only after the audit passes. Test on a small slice first; the full run is the
long step (see the processing-time estimates in `README.md`).

```bash
# 2a. Slice test — 50 images
python run_all.py --image-dir "$CORPUS" --db outputs/flights.db --images 50
python run_all.py --db outputs/flights.db --status

# 2b. Full OCR/DB build over the whole corpus
python run_all.py --image-dir "$CORPUS" --db outputs/flights.db

# 2c. Validate the populated database
python run_all.py --db outputs/flights.db --validate
python run_all.py --db outputs/flights.db --export-pr-intel outputs/pr_intel
```

**Gate:** `--status` should report a screenshot/flight count consistent with
the corpus; `outputs/pr_intel/integration_report.json` `overall_status` should
be `PASS`. A value of `NO_DATA` means the database is still empty.

## Part 3 — Spiderweb operational calibration

See [`SPIDERWEB_OPERATIONAL_CALIBRATION.md`](SPIDERWEB_OPERATIONAL_CALIBRATION.md)
for the full field reference.

```bash
python run_all.py --db outputs/flights.db --export-spiderweb outputs/spiderweb
python run_all.py --spiderweb-intake outputs/spiderweb
python run_all.py --calibrate-scoring outputs/spiderweb
```

**Gate:** inspect `outputs/spiderweb/calibration_report.json`:

- `baseline_mode` should be `operational` (≥50 candidates); `fixture` means the
  database is too small to calibrate.
- `status == "PASS"` → done.
- `status == "FAIL"` → each `calibration_flags` entry names a metric and the
  scoring constant to adjust in `readiness/spiderweb_intake.py` (e.g. `MUNICIPAL_CENTROIDS`,
  `HYDRO_LOCATIONS`, `UTILITY_CORRIDOR_WAYPOINTS`, tier thresholds). Patch the
  constant, re-run Part 3, and repeat until `PASS`.

## Sharing results

The corpus stays local; only small artifacts need to travel. The audit report,
`integration_report.json`, and `calibration_report.json` are all KB-sized —
commit them to a branch (never the raw images; see `DATA_POLICY.md`) so a
review session can help tune scoring constants.

## Verification summary

| Step | Pass condition |
|------|----------------|
| Manifest audit | `fr24_manifest_audit_report.json` → `audit_pass == true` |
| OCR/DB build | `--status` shows the expected screenshot count; `integration_report.json` `overall_status == PASS` |
| Calibration | `calibration_report.json` → `baseline_mode == operational` and `status == PASS` |
