# FAA Aircraft Registry — local data directory

This directory holds a **local, uncommitted** copy of the FAA Releasable
Aircraft Registry database. These files are large public-record datasets that
are intentionally **not committed** to the repository; they are runtime inputs
supplied by the operator.

`scripts/skywatcher_ocr_registry_validation_pass.py` reads the four files below
to validate OCR-recovered FR24 N-number candidates before they are promoted
into `platform_master` or joined to P-Route events.

## Required files

Place these four files directly in `data/faa_registry/`:

| File | Contents |
|---|---|
| `MASTER.txt` | Registered aircraft master records (active registrations) |
| `DEREG.txt` | Deregistered aircraft records |
| `RESERVED.txt` | Reserved-but-unassigned N-numbers |
| `ACFTREF.txt` | Aircraft reference (manufacturer / model lookup by `MFR MDL CODE`) |

These are the standard comma-delimited files distributed inside the FAA
**Releasable Aircraft Registry Database** download (a single ZIP archive from
the FAA registry download page). Unzip it and copy the four files above into
this directory. The loader tolerates the FAA's native headers (it normalizes
`N-NUMBER` → `n_number`, etc.) and falls back across `utf-8-sig` / `latin-1`
encodings, so no pre-processing is required.

## Pipeline inputs (also local / uncommitted)

The validation pass also needs two CSVs produced by the upstream OCR pipeline.
By default it looks for them at the repository root:

| File | Produced by |
|---|---|
| `ocr_new_tails.csv` | OCR candidate tails (e.g. `fr24_ocr_parallel.py` → `fr24_ocr_finalize.py` → `build_new_tails.py`) |
| `events.csv` | FR24 P-Route event rows |

Both accept flexible column names (the loader infers the tail/count/image
columns), and `ocr_new_tails.csv` may be a headerless one-tail-per-line file.

## Running

From the repository root, once the files above are in place:

```bash
python3 scripts/skywatcher_ocr_registry_validation_pass.py \
  --ocr-new-tails ocr_new_tails.csv \
  --events events.csv \
  --faa-dir data/faa_registry \
  --out-dir outputs/registry_validation
```

Outputs are written under `outputs/registry_validation/`
(`registry_validated_tails.csv`, `platform_master_patch.csv`,
`ocr_false_positive_patterns.csv`, `validation_summary.json`). See
`docs/skywatcher_ocr_registry_validation_pass.md` for the classification model
and the P-Route event-join hard gate.

## Do not commit the data files

Only this `README.md` belongs in version control. The FAA `.txt` files and the
generated OCR/event CSVs are local artifacts and must not be committed.
