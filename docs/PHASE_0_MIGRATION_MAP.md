# Phase 0 Migration Map

## Canonical ownership

| Legacy/current path | Phase 0 disposition | Long-term target |
|---|---|---|
| Root aircraft/GIS/bridge modules | Compatibility facade, no path bootstrap | Remove after defined deprecation window |
| `src/skywatcher/` | Canonical installable package | Retain |
| `scripts/` | Executable adapters importing package-qualified modules | Move reusable logic into package incrementally |
| `fr24/` | Existing package retained; path hacks removed | Partition ingestion and analysis in later phases |
| `tools/satim_engine/` | Independently distributable package, archive extraction hardened | Candidate canonical SATIM engine in Phase 2 |
| `tools/satim_route_findings/` | Independently distributable read-only package | Retain |
| Editable `../thehub-pr/packages/*` | Removed | Exact pinned optional packages or a federation workspace |
| `Archive/`, `__MACOSX/`, bytecode/caches | Prohibited by hygiene gate | Never source-controlled or exported |
| Finder-created repository ZIP | Replaced | `skywatcher export-source` deterministic archive |

## Compatibility rules

1. Existing public schemas are unchanged.
2. Existing analytical functions retain signatures unless a security correction requires a stricter boundary.
3. Core install and test collection do not require production data or `thehub-pr`.
4. Federation-enabled installs use exact commit pins.
5. Legacy intent-inference names are not active exports; lazy access warns and remains quarantined.
6. Frontend and production data paths are outside this migration.

## Next migrations

- Phase 1: immutable run manifests, data-pack manifest/doctor, artifact index, structured logging.
- Phase 2: select one canonical SATIM engine and convert repo-native runners into adapters.
- Phase 3: full-assets certification, profiling, release automation, and generated capability documentation.
