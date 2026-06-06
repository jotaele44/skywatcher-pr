# Airspace Producer Export Target

ACTIVE_VECTOR: Puerto Rico Airspace producer export contract

This document defines the target export package for the Puerto Rico Airspace Intelligence Tool as a PRIIS producer repo.

## Boundary

This repo produces airspace/screenshot/flight-event packages.

It does not implement:

- PRIIS hub ingestion,
- Finance and contract reconciliation,
- FOIA queue management,
- Arcadis-style Analysis dossiers,
- production UI/API/database services.

## Required package layout

```text
manifest.json
observations.geojson
observations.csv
sources.json
lineage.json
confidence.json
```

## Observation record fields

| Field | Required | Notes |
|---|---:|---|
| observation_id | yes | Stable unique ID |
| event_datetime | yes | ISO-8601 timestamp |
| location_name | no | Human-readable location label |
| municipality | no | Puerto Rico municipality if known |
| lat | yes | WGS84 latitude |
| lon | yes | WGS84 longitude |
| altitude_ft | no | Altitude if available |
| bearing | no | Direction if available |
| duration_seconds | no | Duration if available |
| signal_type | yes | Example: FR24_SCREENSHOT, ADSB, RADAR, FIELD_REPORT |
| description_summary | no | Short neutral description |
| source_id | yes | Must link to sources.json |
| source_type | yes | screenshot, adsb, radar, official, field_note, secondary |
| evidence_tier | yes | T1, T2, T3, or T4 |
| confidence | yes | 0.0 to 1.0 |
| geometry_status | yes | located, approximate, unlocated, invalid |
| temporal_status | yes | exact, approximate, missing, invalid |
| lineage_id | yes | Must link to lineage.json |
| synthetic | yes | Boolean test/prod separation flag |

## Evidence tiers

| Tier | Meaning |
|---|---|
| T1 | Technical, sensor-derived, official, or machine-verifiable evidence |
| T2 | Operational or official structured source |
| T3 | Witness, field observation, or analyst note |
| T4 | Secondary/context/lead-generation only |

## Validation rules

Fail if:

- manifest.json is missing,
- schema_version is missing,
- observations file is missing,
- source_id is missing,
- lineage_id is missing,
- confidence is missing or outside 0.0 to 1.0,
- event_datetime is missing or unparsable,
- evidence_tier is not T1/T2/T3/T4,
- lat/lon is missing for located or approximate records,
- geometry_status is unsupported,
- temporal_status is unsupported,
- synthetic=true appears in production mode,
- source provenance is missing,
- lineage metadata is missing.

## Production mode rule

Synthetic fixtures are allowed only in test mode.

Production validation must fail closed if any observation has:

```json
"synthetic": true
```

## Test package requirement

The synthetic fixture package must pass in test mode and fail in production mode.

## Future extension queue

1. screenshot inventory with SHA-256,
2. manual review queue,
3. route extraction,
4. coordinate uncertainty model,
5. integration report,
6. hub export adapter.
