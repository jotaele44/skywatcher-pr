# Federation Reach Expansion — Canonical Observations, Alerts, and a Consumer Bridge

This change widens Skywatcher's participation in the PRII artifact federation
(hub-and-spoke via `thehub-pr`) in two directions:

1. **Producer reach** — the federation export now emits two additional canonical
   streams, `observations` and `alerts`, alongside the existing
   `sources` / `entities` / `relationships`.
2. **Consumer reach** — a new Skywatcher-side bridge ingests hub-canonical
   packages emitted by *sibling* producers, so airspace analysis can be
   cross-referenced against sibling signals inside Skywatcher.

No screenshot processing, no live tracking, no operational cueing is added.
Every new row is an analytical review candidate.

## 1. Producer: `observations` stream (FE1)

`scripts/federation_export.py` now projects each airspace observation onto a
canonical `observations` row conforming to the Hub's
`federation_observation.schema.json`:

- deterministic id `obs_<32hex>` (`prii_export_utils.fid`);
- `observation_type` = the observation's `signal_type` projected to a stable
  slug (e.g. `FR24_SCREENSHOT` → `fr24_screenshot`);
- `entity_id` anchors the row to the matching `airspace_observation` entity;
- `location` carries the WGS84 point (+ `altitude_ft`) and `municipality`;
- airspace-specific fields (`signal_type`, `evidence_tier`, `geometry_status`,
  `temporal_status`, `bearing`, `duration_seconds`, `callsign`, `operator`, …)
  ride in `attributes` rather than being dropped.

This gives the Hub's `correlate_observations` stage first-class Skywatcher rows
to join to sibling producers by `location.municipality` — previously the
observation existed only as a flattened `entities` row.

## 2. Producer: `alerts` stream (FE2)

Airspace anomaly alerts are projected onto the Hub's
`federation_alert.schema.json` as `alrt_<32hex>` rows. Alerts arrive as an
**optional package input** (`alerts.json`) — the same optional-input pattern as
`airfields.json` / `hangar_zones.json` / `endpoint_events.json` — so the
exporter never fabricates an anomaly; it only projects producer-declared ones.

- `severity` is clamped to `[0,5]`; unknown `status` falls back to `draft`;
- `entity_id` optionally anchors the alert to its `airspace_observation` entity;
- `location` + `municipality` drive the Hub's `correlate_alerts`
  (`alert_affects_entity`) stage;
- every alert is stamped with the review-only guardrail posture
  (`operator_action=review_context_only`, `operational_cueing=false`,
  `live_tracking=false`, `tactical_public_tracking=false`,
  `confirmation_status=not_confirmed`) as defense-in-depth.

## 3. Consumer bridge (FE3)

`integration/federation_consumer.py` is the reciprocal of the export: it ingests
a hub-canonical package emitted by a **sibling** producer (e.g. `aguayluz-pr`
grid/water alerts, `spiderweb-pr` spatial observations) so Skywatcher can
cross-reference sibling signals — by shared `location.municipality` — against its
own airspace observations.

It models the three cross-producer signal streams: `observations`, `alerts`,
`entities` (validated against the canonical Hub schemas, now vendored into
`schemas/` as the shared-schema federation pattern). Unmodeled streams
(`sources`, `relationships`, …) are recorded as `skipped`, not silently dropped.

Policy (candidate-only, mirrors the Spiderweb consumer bridge):

- `manifest.json` is required; each modeled file's `record_count` and `sha256`
  are verified against the bytes on disk, so a tampered or hand-assembled JSONL
  is rejected rather than trusted;
- every record is validated against its canonical Hub schema; invalid records
  are held (never ingested);
- defense-in-depth: any record carrying a terminal-accept label
  (`confirmed`, `verified_event`, …) is rejected even if schema-valid — bare
  alert-lifecycle states (`validated`, `active`, `closed`) are legitimate and
  intentionally not treated as terminal-accept;
- ingestion is transactional into a minimal read-model
  (`consumed_observations` / `consumed_alerts` / `consumed_entities` +
  a `consumed_producers` provenance row). No screenshot processing.

## Files

| File | Change |
|---|---|
| `scripts/federation_export.py` | emit `observations` + `alerts` streams |
| `exports/examples/synthetic_airspace_package/alerts.json` | synthetic alert fixture |
| `schemas/federation_observation.schema.json` | vendored Hub schema (shared) |
| `schemas/federation_alert.schema.json` | vendored Hub schema (shared) |
| `schemas/federation_entity.schema.json` | vendored Hub schema (shared) |
| `integration/federation_consumer.py` | new sibling-producer consumer bridge |
| `tests/test_federation_export.py` | FE1/FE2 stream + Hub-schema-validation tests |
| `tests/test_federation_consumer.py` | FE3 accept / reject / integrity tests |

## Verification

- `pytest tests/test_federation_export.py tests/test_federation_consumer.py -q`
  — 25 passing (structure, deterministic ids, Hub-schema validation, severity
  clamp, sha256/count integrity, prohibited-label gate, dry-run).
- Every emitted `observations` / `alerts` row validates against the canonical
  Hub schema; the manifest validates against `federation_export_manifest`.
- Full suite green (777 passed / 16 dep-skipped).
