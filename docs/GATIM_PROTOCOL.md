# GATIM Protocol v1

GATIM (Geographic Anomaly and Terrain Intelligence Model) is a sibling protocol to SATIM for non-flight satellite imagery, map pins, geographic CSV exports, and fixed-location review queues.

## Boundary

GATIM produces candidate-site ledgers. It does not confirm anomalous activity, underground structures, flight behavior, or intent. Rows are review candidates until corroborated by independent evidence.

## Pipeline

1. `GATIM-Ingest` reads runtime CSV/KML/GeoJSON/GPX/screenshot/PDF-derived location exports.
2. `GATIM-Normalize` extracts title, note, URL, tags, comments, and coordinates.
3. `GATIM-Dedupe` clusters direct-coordinate rows by a configurable radius; v1 default is 5 meters.
4. `GATIM-Classify` assigns conservative classes: `ILAP`, `ACCESS`, `INFRASTRUCTURE`, `TERRAIN_ANOMALY`, or `UAP_CASE_ANCHOR`.
5. `GATIM-ReviewQueue` ranks rows into review buckets without promoting conclusions.
6. `GATIM-SATIM-Link` emits read-only proximity links from fixed POIs to SATIM FN points.

## Runtime command

```bash
python -m tools.gatim.cli \
  --input-dir data/gatim/raw \
  --out-dir outputs/gatim \
  --dedupe-radius-m 5
```

Raw candidate CSVs are runtime inputs and should not be committed unless reduced to sanitized fixtures.

## Ledger fields

| Field | Purpose |
|---|---|
| `gatim_id` | Stable row identifier from source filename, row number, title, and URL. |
| `source_file` / `source_dataset` | Runtime source provenance. |
| `lat` / `lon` | Normalized coordinate when embedded in URL/title/note. |
| `coord_status` | `direct`, `needs_geocode`, or `missing`. |
| `dedupe_cluster_id` | 5m coordinate-cluster ID. |
| `class_primary` | Conservative review class. |
| `evidence_tier` | Seed-candidate evidence tier, not a confirmation tier. |
| `visual_features` | Keyword-derived review hints such as road, water, structure, terrain cut, or pad. |
| `grid_id` | Rounded spatial tile key. |
| `satim_link_status` | `none`, `nearby_FN`, or `confirmed_overlap` as spatial overlap only. |
| `review_priority` | Queue bucket such as `P0_REVIEW`, `P1_REVIEW`, or `P3_GEOCODE`. |
| `confidence` | Candidate processing confidence, capped below certainty. |

## Guardrails

- No raw uploaded candidate data in the repository.
- No confirmed-anomaly language in code, docs, tests, or generated queue labels.
- Treat conclusion-heavy input labels as candidate taxonomy only.
- SATIM can raise GATIM review priority through spatial proximity, but cannot confirm fixed-site meaning.
- GATIM can provide fixed POI context to SATIM, but cannot confirm flight behavior.
- Do not use this module for personal targeting or private residence profiling.

## SATIM/GATIM interface

The bridge is read-only. It accepts GATIM rows and SATIM FN point dictionaries with `fn_id`, `lat`, and `lon`. It returns candidate proximity links:

- `nearby_FN`: within configured radius.
- `confirmed_overlap`: coordinate overlap only; this does not confirm causation or site meaning.

Shared join keys should remain explicit: `gatim_id`, `grid_id`, `fn_id`, `distance_m`, and `link_status`.
