# Skywatcher OCR Registry Validation Pass

## Vector

`SKYWATCHER_OCR_REGISTRY_VALIDATION_PASS`

## Purpose

Validate OCR-recovered FR24 N-number candidates before they are merged into `platform_master` or joined into the P-Route event layer.

This pass is designed to catch:

- FAA-invalid N-number formats.
- OCR confusion involving `I`, `O`, `0`, and short registrations.
- Reserved-only N-numbers misread as high-frequency active aircraft.
- Deregistered aircraft that need screenshot-date review.
- Sale-reported aircraft that should be held before promotion.
- Registry-negative high-frequency paradoxes such as `N253TH`.

## Required local inputs

Expected default paths from repo root:

```bash
ocr_new_tails.csv
events.csv
data/faa_registry/MASTER.txt
data/faa_registry/DEREG.txt
data/faa_registry/RESERVED.txt
data/faa_registry/ACFTREF.txt
```

## Command

```bash
python3 scripts/skywatcher_ocr_registry_validation_pass.py \
  --ocr-new-tails ocr_new_tails.csv \
  --events events.csv \
  --faa-dir data/faa_registry \
  --out-dir outputs/registry_validation
```

## Outputs

```bash
outputs/registry_validation/registry_validated_tails.csv
outputs/registry_validation/platform_master_patch.csv
outputs/registry_validation/ocr_false_positive_patterns.csv
outputs/registry_validation/validation_summary.json
```

## Classification model

| Class | Meaning | Default promotion state |
|---|---|---|
| `CONFIRMED_ACTIVE` | Tail exists in FAA `MASTER.txt` and is not sale-reported | `promote` |
| `SALE_REPORTED` | Tail exists in `MASTER.txt` but sale/certificate text appears unstable | `hold` |
| `RESERVED_ONLY` | Tail exists only in `RESERVED.txt` | `reject` |
| `DEREGISTERED` | Tail exists in `DEREG.txt` | `hold` |
| `OCR_SUSPECT` | Invalid format or registry-negative candidate | `hold` or `reject` |
| `SHORT_TAIL_EDGE` | Legal-format short N-number but registry-negative | `hold` |

## Hard gate

Do not run the P-Route event join until:

1. `registry_validated_tails.csv` is reviewed.
2. `ocr_false_positive_patterns.csv` is used to suppress recurring OCR artifacts.
3. `platform_master_patch.csv` is accepted or manually edited.
4. `N253TH` is confirmed quarantined.

## Recommended post-run checks

```bash
python3 scripts/skywatcher_ocr_registry_validation_pass.py \
  --ocr-new-tails ocr_new_tails.csv \
  --events events.csv \
  --faa-dir data/faa_registry \
  --out-dir outputs/registry_validation | tee outputs/registry_validation/run.log

python3 - <<'PY'
import csv
from collections import Counter
p='outputs/registry_validation/registry_validated_tails.csv'
rows=list(csv.DictReader(open(p)))
print('rows', len(rows))
print('class', Counter(r['registry_class'] for r in rows))
print('promotion', Counter(r['promotion_status'] for r in rows))
print('N253TH', [r for r in rows if r['tail']=='N253TH'])
PY
```

## Merge rule

Only `promotion_status=promote` should flow into the next automated platform update. `hold` rows require manual review; `reject` rows must not enter `platform_master`.
