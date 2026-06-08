# FR24 OCR Analysis Vector and Temporal Wave Grouping

## Purpose

This layer adds two read-only analytical stages on top of field-selected OCR candidates:

1. **Analysis vector** — converts each candidate row into a named multi-dimensional
   feature vector (field presence, confidence, conflict signals, temporal parse quality,
   quality tier). This replaces the collapsed scalar `confidence_score` with preserved
   individual dimensions for downstream use.

2. **Temporal wave grouping** — groups observations by aircraft identity (registration
   → callsign → image name) and orders them by parsed playback timestamp to form
   "waves" of same-aircraft observations across time.

All outputs remain candidate records. No event is confirmed by this layer.

## Run

```bash
python fr24/ocr_analysis_vector.py \
  --input-csv data/_manifests/fr24_audit/fr24_event_candidates_selected.csv \
  --output-dir data/_manifests/fr24_audit
```

### Outputs

| File | Purpose |
|---|---|
| `fr24_ocr_analysis_vectors.csv` | Per-candidate rows with all source fields + vector columns appended |
| `fr24_temporal_waves.csv` | One row per aircraft identity with wave aggregate columns |
| `fr24_analysis_vector_summary.json` | Candidate count, wave count, tier distribution |

## Analysis vector columns

All columns are prefixed `vector_`.

### Field presence (binary 0/1)

| Column | Source field |
|---|---|
| `vector_has_callsign` | `callsign_or_label` |
| `vector_has_operator` | `operator` |
| `vector_has_aircraft_type` | `aircraft_type` |
| `vector_has_registration` | `registration` |
| `vector_has_origin` | `origin_code` |
| `vector_has_destination` | `destination_code` |
| `vector_has_altitude` | `barometric_altitude_ft` |
| `vector_has_speed` | `ground_speed_mph` |
| `vector_has_flight_status` | `flight_status` |
| `vector_has_elapsed_departed` | `elapsed_departed` |
| `vector_has_elapsed_arrived` | `elapsed_arrived` |
| `vector_has_playback_date` | `playback_date` |
| `vector_has_playback_time` | `playback_time` |
| `vector_has_playback_tz` | `playback_timezone` |

### Aggregate quality

| Column | Description |
|---|---|
| `vector_field_coverage` | Fraction of 14 fields populated (0.0–1.0) |
| `vector_whole_confidence` | OCR whole-image confidence |
| `vector_region_confidence` | OCR region confidence |
| `vector_max_confidence` | max(whole, region) |

### Conflict signals

| Column | Description |
|---|---|
| `vector_conflict_count` | Raw conflict count from upstream fusion |
| `vector_conflict_normalized` | `conflict_count / 14`, capped at 1.0 |
| `vector_has_disagreements` | 1 if `selected_field_disagreements` is non-empty |

### Temporal

| Column | Description |
|---|---|
| `vector_temporal_parsed` | 1 if `playback_date` parsed to a datetime successfully |
| `vector_playback_iso` | ISO-8601 combined playback timestamp, or empty |
| `vector_aircraft_identity` | Registration if present, else callsign, else image name |

### Quality tier

| Tier | Condition |
|---|---|
| 1 (high) | `field_coverage ≥ 0.70` and `conflict_count == 0` and no disagreements |
| 2 (medium) | `field_coverage ≥ 0.40` and `conflict_count ≤ 2` |
| 3 (low) | `field_coverage ≥ 0.15` |
| 4 (minimal) | Below all thresholds |

### Policy columns

| Column | Value |
|---|---|
| `vector_confirmation_status` | `not_confirmed` (always) |
| `vector_version` | `fr24_ocr_analysis_vector_v0.1.0` |

## Wave columns

All columns are prefixed `wave_`.

| Column | Description |
|---|---|
| `wave_id` | Unique wave identifier (`wave_000001`, …) |
| `wave_aircraft_identity` | Grouping key (registration, callsign, or image name) |
| `wave_obs_count` | Number of screenshots for this identity |
| `wave_earliest_iso` | ISO timestamp of earliest observation |
| `wave_latest_iso` | ISO timestamp of latest observation |
| `wave_duration_minutes` | `(latest − earliest)` in minutes |
| `wave_avg_field_coverage` | Mean `vector_field_coverage` across observations |
| `wave_avg_confidence` | Mean `vector_max_confidence` across observations |
| `wave_temporal_coherence` | 1 if all observations have a parsed timestamp |
| `wave_confirmation_status` | `not_confirmed` (always) |
| `wave_version` | `fr24_ocr_analysis_vector_v0.1.0` |

## Labels

### Allowed

- `not_confirmed`

### Prohibited

- `confirmed`
- `confirmed_aircraft_event`
- `confirmed_anomaly`
- `confirmed_route`
- `verified_event`
- `validated_aircraft_event`

## Recommended local validation

```bash
python3 -m py_compile fr24/ocr_analysis_vector.py

# Smoke run (empty input)
python3 fr24/ocr_analysis_vector.py \
  --input-csv /dev/null \
  --output-dir /tmp/vector_smoke

# Unit tests
python3 -m pytest tests/test_fr24_analysis_vector.py -v
```

## Next step

Run `fr24/wave_validator.py` to validate temporal and physical coherence
within each multi-obs wave (altitude climb rates, speed plausibility,
monotonic timestamps).
