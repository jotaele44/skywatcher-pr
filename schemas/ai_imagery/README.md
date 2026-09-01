# Skywatcher AI and imagery domain contracts

These schemas freeze the aviation-domain side of ADR 0006 without adding provider execution or network behavior.

- `aviation_vision_extraction.v1.schema.json` defines provider-neutral provisional aviation fields and requires external provenance references.
- `skywatcher_producer_package.v2.schema.json` defines the deterministic artifact-only package envelope and complete accounting.

TheHub owns the referenced acquisition, model-run and field-provenance records. Skywatcher owns only the aviation extraction and producer-package representation.
