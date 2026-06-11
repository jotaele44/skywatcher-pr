# Airspace Schema Reference

Field-by-field reference for the four federation streams. The authoritative
definitions are the JSON Schemas under `schemas/spiderweb_*.schema.json`; this
document explains intent and gives examples.

## Common fields (every stream)

| Field        | Type     | Required | Notes |
|--------------|----------|----------|-------|
| `id`         | string   | yes      | Deterministic 32-char hex sha256; see export_contract.md |
| `source_id`  | string   | yes      | References a row in `sources.jsonl` |
| `lineage`    | array    | yes      | Non-empty; see `lineage_model.md` |
| `confidence` | object   | yes      | `{score, method, components?}`; see `confidence_model.md` |
| `attributes` | object   | no       | Free-form per-stream extension |
| `is_synthetic` | boolean | no      | Default `false`; `true` is rejected in production mode |

## `spiderweb_event` — `airspace_events.jsonl`

| Field         | Type     | Required | Notes |
|---------------|----------|----------|-------|
| `event_type`  | string   | yes      | e.g. `takeoff`, `landing`, `corridor_crossing`, `alert_raised` |
| `event_time`  | string   | yes      | ISO-8601 with timezone |
| `geometry`    | object   | yes      | GeoJSON `Point` / `LineString` / `Polygon` |

Example:

```json
{
  "id": "58490aa1c6d06e29ea10561f01d0e9d2",
  "source_id": "src_fr24_2024_03_15_a",
  "event_type": "takeoff",
  "event_time": "2024-03-15T08:00:00+00:00",
  "lineage": [...],
  "confidence": {"score": 0.81, "method": "rule_based"},
  "geometry": {"type": "Point", "coordinates": [-66.0018, 18.4373]},
  "attributes": {"callsign": "N5854Z", "airport": "SJU"},
  "is_synthetic": true
}
```

## `spiderweb_observation` — `observations.jsonl`

| Field              | Type     | Required | Notes |
|--------------------|----------|----------|-------|
| `subject_id`       | string   | no       | If known, the observed entity (callsign, MMSI, etc.) |
| `observation_type` | string   | yes      | e.g. `fr24_frame`, `ais_ping`, `adsb_report` |
| `observed_at`      | string   | yes      | ISO-8601 with timezone |
| `geometry`         | object   | yes      | GeoJSON `Point` / `LineString` / `Polygon` |

## `spiderweb_track` — `tracks.jsonl`

| Field         | Type     | Required | Notes |
|---------------|----------|----------|-------|
| `subject_id`  | string   | yes      | Tracks are always attributed to a subject |
| `observed_at` | string   | yes      | Start of the track segment, ISO-8601 with timezone |
| `path`        | object   | yes      | GeoJSON `LineString` with at least 2 `[lon, lat]` or `[lon, lat, alt]` points |

## `spiderweb_source` — `sources.jsonl`

| Field           | Type     | Required | Notes |
|-----------------|----------|----------|-------|
| `kind`          | string   | yes      | e.g. `fr24_screenshot`, `ais`, `adsb`, `manual` |
| `first_seen_at` | string   | yes      | ISO-8601 with timezone |
| `last_seen_at`  | string   | yes      | ISO-8601 with timezone |

A `sources.jsonl` row is the system-of-record for the `source_id` value used
by events/observations/tracks. Consumers can dereference any `source_id` by
joining on the `source_id` field in this stream.

## Coordinate conventions

- GeoJSON ordering: `[longitude, latitude]` (not lat/lon).
- Longitude in `[-180, 180]`, latitude in `[-90, 90]`.
- Optional third value in a coordinate tuple is altitude/elevation in meters.

## Timestamp conventions

- ISO-8601 with explicit timezone (UTC strongly preferred: `+00:00` or `Z`).
- Naive (TZ-less) timestamps are rejected by `validate_export.py`.
