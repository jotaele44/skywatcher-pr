# SATIM Batch Reproducibility Guardrails

SATIM batch graph output must remain stable across ordinary corpus changes.

## Guardrails

- Do not use Python `hash()` for persisted identifiers.
- Do not use global DataFrame indexes in persisted identifiers.
- Use deterministic digest inputs.
- Use source-local ordinals for repeated vertices from the same source.
- Sort source groups before graph emission.
