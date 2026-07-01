# Skywatcher Sensor Fusion Patch Readiness

## Vector

`SKYWATCHER_SENSOR_FUSION_IMPLEMENTATION_v1`

## Implemented

- Added canonical air event schema.
- Added maritime baseline schema with historical/context-only semantics.
- Added coastal corridor event schema.
- Added cross-domain overlap schema.
- Added source registry entries for airspace and maritime baseline/context sources.
- Added air event normalizer under `src/skywatcher/normalizers/`.
- Added Puerto Rico aggregate corridor index under `src/skywatcher/fusion/`.
- Added cross-domain overlap scoring under `src/skywatcher/fusion/`.
- Added tests for air event normalization, corridor attachment, overlap scoring, and policy guard behavior.

## Guardrails

- Air records are forced to include `tactical_public_tracking: false`.
- Maritime/coastal context records are treated as historical/baseline context, not live operational tracking.
- Cross-domain overlap suppresses disallowed air records and disallowed context records.
- Outputs are explanation-bearing analytical review candidates, not operational cues.

## Blocked / Adjusted

- A detailed maritime event schema and detailed external corridor CSV were intentionally not added after connector safety checks blocked payloads resembling vessel-level tracking or route registry data.
- Maritime implementation was narrowed to `maritime_baseline.schema.json` and aggregate context IDs.

## Validation

Remote branch comparison:

- Base: `main`
- Head: `gpt/airspace-maritime-sensor-fusion`
- Status: ahead of main, not behind main

Required local/CI command:

```bash
pytest
```

The GitHub connector used for this patch does not expose remote command execution, so pytest must run through CI or a local checkout.
