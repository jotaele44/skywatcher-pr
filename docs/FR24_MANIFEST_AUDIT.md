# FR24 Manifest Audit

## Purpose

This document defines the pre-ingest audit gate for the raw FlightRadar24 screenshot corpus exported from Google Photos Takeout.

The audit happens before any OCR, screenshot parsing, SQLite database generation, or Spiderweb operational calibration.

## Frozen Boundary

Do not start these steps until the audit passes:

- OCR extraction
- screenshot-to-DB generation
- `--export-spiderweb`
- `--spiderweb-intake`
- `--calibrate-scoring`

The audit is read-only. It does not modify images, sidecar JSON files, databases, or repository files.

## Local Command

Run the audit on the Mac that has the raw image folder:

```bash
python fr24/manifest_audit.py --root "/Users/jotaele/Documents/GitHub/Raw Flight Logs/Takeout-9/Google Photos/FR24" --output-dir /tmp/fr24_audit --max-images 50
python fr24/manifest_audit.py --root "/Users/jotaele/Documents/GitHub/Raw Flight Logs/Takeout-9/Google Photos/FR24" --output-dir /tmp/fr24_audit
```

## Outputs

| File | Purpose |
|---|---|
| `fr24_manifest_audit.csv` | Per-image manifest with path, size, hash, dimensions, duplicate flag, corrupt flag, and sidecar flag |
| `fr24_manifest_audit_report.json` | Summary report used as the pipeline gate |

## Pass Criteria

The audit passes only when:

| Field | Required |
|---|---:|
| `corrupt` | `0` |
| `db_files_in_tree` | `[]` |
| `git_tracked_raw_files` | `[]` |

Duplicate images and missing Google Photos sidecars are reported, but they do not automatically fail the audit. They should be reviewed before OCR if the counts are unusually high.

## Failure Remediation

| Failure | Action |
|---|---|
| Corrupt images | Quarantine or remove before OCR |
| DB files in raw tree | Move outside the image tree |
| Git-tracked raw files | Add ignore rules and untrack with `git rm --cached` |
| High duplicates | Decide whether to deduplicate before OCR |
| Many missing sidecars | Verify Google Takeout extraction completeness |

## Resume Condition

Only after `audit_pass=true` should the next vector begin:

```text
RAW_FR24_SCREENSHOTS → screenshot inventory → OCR / extraction → operational SQLite DB → --export-spiderweb → --spiderweb-intake → --calibrate-scoring
```
