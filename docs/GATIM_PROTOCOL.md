# GATIM Protocol v1

GATIM is a sibling protocol to SATIM for non-flight satellite imagery, map pins, geographic CSV exports, and fixed-location review queues.

## Canonical layout

```text
tools/gatim/
  runner.py
  cli.py
  core/
  exports/
  interfaces/
  audit/
  schemas/
tests/gatim/
  fixtures/sanitized_seed/
```

Flat modules remain as compatibility wrappers where needed. New development should target the canonical subpackages.

## Pipeline

1. Normalize input rows.
2. Cluster direct-coordinate rows by 5 meters by default.
3. Assign conservative review classes.
4. Rank the review queue.
5. Export CSV, GeoJSON, and geocode-hold outputs.
6. Emit SATIM/GATIM spatial links as read-only proximity context.

## Runtime command

```bash
python -m tools.gatim.cli \
  --input-dir data/gatim/input \
  --out-dir outputs/gatim \
  --dedupe-radius-m 5 \
  --files uap.csv access.csv ilap.csv poi.csv recon.csv anomaly.csv
```

Source CSVs are runtime inputs and should not be committed unless reduced to sanitized fixtures.

## Outputs

| Output | Purpose |
|---|---|
| `GATIM_CALIBRATION_LEDGER_v1.csv` | Full normalized ledger. |
| `GATIM_REVIEW_QUEUE_v1.csv` | Ranked review queue with reason and next action. |
| `GATIM_GEOCODE_QUEUE_v1.csv` | Rows requiring coordinate resolution or hold. |
| `GATIM_CANDIDATES_v1.geojson` | Direct-coordinate rows as GIS-ready points. |
| `GATIM_REVIEW_QUEUE_v1.geojson` | Review-ready direct-coordinate points. |

## Schemas

- `tools/gatim/schemas/gatim_candidate_schema.json`
- `tools/gatim/schemas/gatim_review_queue_schema.json`
- `tools/gatim/schemas/satim_gatim_link_schema.json`

## Guardrails

- Keep source data out of the repository.
- Avoid conclusion language in code, docs, tests, or output labels.
- Treat strong input labels as review taxonomy only.
- SATIM can raise GATIM review priority through spatial proximity.
- GATIM can provide fixed POI context to SATIM.
- Do not use this module for personal targeting.

## SATIM/GATIM interface

The bridge is read-only. It accepts GATIM rows and SATIM FN point dictionaries with `fn_id`, `lat`, and `lon`. It returns proximity links only:

- `nearby_FN`: within configured radius.
- `coordinate_overlap`: close coordinate match only.

Shared join keys should remain explicit: `gatim_id`, `grid_id`, `fn_id`, `distance_m`, `link_status`, and `link_note`.
