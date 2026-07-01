# SATIM Stable ID Policy

SATIM graph IDs must be reproducible across repeated runs and resilient to unrelated batch composition changes.

## Track IDs

Track IDs are derived from the source path.

## Vertex IDs

Vertex IDs are derived from:

- source path
- per-source ordinal after source-local index reset
- latitude
- longitude
- timestamp

They must not use Python `hash()` or global DataFrame indexes.
