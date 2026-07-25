# FR24 Segment Provenance Model

This model separates rendered route color from inferred source and transmission continuity.
Bright FR24 route pixels are evidence that a line was rendered, not proof that ADS-B reception was continuous.

## Guardrails

- Color never vetoes an offline or interpolation classification.
- At least two non-color signals are required for `PROBABLE_OFFLINE`.
- Screenshot-only confidence is capped at 0.79.
- `CONFIRMED_OFFLINE` requires independent or structured corroboration.
- Source fusion is represented as `SOURCE_TRANSITION`, not automatically as offline.

## SATIM boundary

The classifier lives in `fr24/`. SATIM may reference the resulting artifact as adjacent provenance, but the terrain/imagery output contract remains unchanged.
