# Skywatcher FR24 Database Schema

**Schema version:** 1 (migration `0001` — base FR24 canonical schema).
**DDL:** `schemas/database_schema.sql`.
**Access/init:** `src/skywatcher/fr24/database.py`, `database_migrations.py`,
`scripts/init_database.py`, CLI `run_all.py --init-db`.

## Configuration precedence
- DB path: `--db PATH` → `SKYWATCHER_DB` → `./data/skywatcher.db`

## Initializer guarantees
Deterministic · idempotent · transactional (per-migration) · migration-aware ·
`schema_version`-tracked · foreign-keys ON · safe (never overwrites data;
all DDL `IF NOT EXISTS`) · validation-only mode (`--validate`) · explicit errors ·
tested with temporary databases only. **No operational `skywatcher.db` is
produced by this task.**

## Tables (10)
| # | Table | Purpose | Key columns |
|---|---|---|---|
| 1 | `schema_version` | migration ledger (append-only) | `version` PK, `applied_at` |
| 2 | `ingestion_batches` | one row per ingest run (append-only) | `batch_id` PK, `status`, `source_ref` |
| 3 | `screenshots` | one row per unique image | `screenshot_id` PK, `sha256` UNIQUE NOT NULL |
| 4 | `ocr_observations` | append-only raw OCR (immutable `raw_text`) | FK `screenshot_id`, `confidence_mean`, `parser_version` |
| 5 | `aircraft` | canonical aircraft identity | `registration` partial-unique, `identity_status` |
| 6 | `flights` | reconstructed flights | `flight_id` PK, gated `mission_status`, `coordinate_method` (widened), `review_status` |
| 7 | `flight_screenshots` | flight↔screenshot junction | UNIQUE(`flight_id`,`screenshot_id`) |
| 8 | `track_points` | ordered geo points | FK `flight_id`, `coordinate_method`+`coordinate_confidence` |
| 9 | `anomalies` | derived anomaly flags | `severity` CHECK, `review_status` |
| 10 | `processing_failures` | structured error accounting (append-only) | `stage`, `reason`, `occurred_at` |

## Preserved invariants
SHA-256 provenance (`screenshots.sha256`) · UTC timestamps · source references ·
OCR confidence · coordinate method + confidence (widened enum, contradiction C5) ·
parser version · review status · append-only ingestion history · explicit foreign
keys (`PRAGMA foreign_keys=ON`) · indexes + uniqueness constraints.

## Reconciliation
Merges the two previously divergent schemas — RLSM `data/rlsm/schema.sql`
(INTEGER-PK `screenshots` + `sha256 UNIQUE`) and the ad-hoc FlightDatabase tables
(TEXT-sha256-PK `screenshots`, `flights`, `track_points`, `aircraft_profiles`) —
adopting the RLSM `screenshots` base and folding FlightDatabase columns into
`flights`/`track_points`/`aircraft`.
