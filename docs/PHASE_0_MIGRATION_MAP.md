# Phase 0 Migration Map

## Canonical ownership

| Legacy/current path | Phase 0 disposition | Long-term target |
|---|---|---|
| Root aircraft/GIS/bridge modules | Compatibility facade with no path bootstrap | Remove after a defined deprecation window |
| `src/skywatcher/` | Canonical installable package | Retain |
| `src/skywatcher/core/repository_policy.py` | Canonical tracked-file and source-export policy | Retain as the single policy source |
| `src/skywatcher/core/repository_export.py` | Deterministic, mode-preserving source export | Retain |
| `src/skywatcher/core/safe_archive.py` | Canonical archive-safety contract | Retain |
| `scripts/` | Thin executable adapters importing package-qualified modules | Move remaining reusable logic into packages incrementally |
| `fr24/` | Existing package retained; path hacks removed | Partition ingestion and analysis in later phases |
| `tools/satim_engine/` | Independently distributable package using the same archive contract | Candidate canonical SATIM engine in Phase 2 |
| `tools/satim_route_findings/` | Independently distributable read-only package | Retain |
| Editable `../thehub-pr/packages/*` | Removed from project metadata, locks, and workflows | Exact pinned optional packages or a future federation workspace |
| `Archive/`, `__MACOSX/`, bytecode, caches, build and coverage output | Prohibited by canonical hygiene gate | Never source-controlled or exported |
| Finder-created repository ZIP | Replaced | `skywatcher export-source` deterministic archive |
| Legacy known-aircraft metadata | Identifier retained; unverified fields inactive | Field-level provenance registry |
| Diagnostic API global dictionaries | Encapsulated thread-safe process overlay | Durable or session-scoped review store in a later phase |

## Compatibility rules

1. Existing public analytical schemas are unchanged.
2. Existing analytical signatures are retained unless a security boundary requires stricter behavior.
3. Core installation and test collection do not require production data or a sibling TheHub checkout.
4. Federation-enabled installs use exact immutable commit references.
5. Legacy intent-inference names are not active exports; lazy compatibility access remains quarantined and warning-emitting.
6. Aircraft identifiers resolve by normalized exact match or an explicit alias only.
7. Owner/operator identity fields remain inactive unless field-level provenance is complete.
8. Mission, purpose, schedule, target, typical operating area, and operational-pattern cueing are never inferred.
9. The CLI requires repository assets for repository validation and fails closed when they are absent.
10. Existing archive destinations are refused by default; explicit replacement is recoverable.
11. Diagnostic review IDs are server-owned and immutable.
12. Remediation-authored changes do not modify frontend or production-data paths.

## Test-tier ownership

| Tier | Purpose |
|---|---|
| Backend core | Clean install, no production data, no TheHub checkout, Python 3.10–3.13 |
| Full-data CI | Repository integration and preserved 55% coverage floor, Python 3.10–3.12 |
| Federation contract | Exact-pinned TheHub shared packages and export compatibility |
| Nested tools | Independent SATIM engine and route-findings distributions |
| Security | CodeQL, secret scan, pip-audit, immutable lock validation |
| Desktop | Frozen application smoke and packaging on Ubuntu, macOS, and Windows |

## Next migrations

- Phase 1: immutable run manifests, data-pack manifest/doctor, artifact index, cache invalidation, and structured logging.
- Phase 2: select one canonical SATIM engine and convert repo-native runners into adapters.
- Phase 3: full-assets profiling, release automation, generated capability documentation, and gating the existing lint/type backlog.
- Later review-store phase: durable, user/session-scoped review records without weakening the read-only default.
