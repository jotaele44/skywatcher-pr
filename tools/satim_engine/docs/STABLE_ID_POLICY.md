# SATIM Stable ID Policy

SATIM graph IDs must be reproducible across repeated runs.

## Rules

- Do not use Python `hash()` for persisted identifiers.
- Do not use batch-global DataFrame row indexes for persisted identifiers.
- Use deterministic digest inputs.
- Use source-local ordinals for repeated vertices from the same source.
