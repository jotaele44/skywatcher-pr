# Phase 0 Migration Map

## Canonical ownership

| Legacy/current path | Phase 0 disposition | Long-term target |
|---|---|---|
| Root aircraft/GIS/bridge modules | Compatibility facades with no runtime path bootstrap | Remove after a defined deprecation window |
| `src/skywatcher/` | Canonical installable package | Retain |
| `src/skywatcher/core/repository_policy.py` | Canonical tracked-file and source-export policy | Retain as the single policy source |
| `src/skywatcher/core/repository_export.py` | Deterministic, mode-preserving source export | Retain |
| `src/skywatcher/core/safe_archive.py` | Canonical archive-safety contract | Retain |
| `tools/satim_engine/src/satim_engine/safe_archive.py` | Independently distributable parity implementation | Consolidate only when package ownership permits a shared dependency without circularity |
| `src/skywatcher/core/known_operators.py` | Exact identifier registry; unverified legacy identity fields inactive | Populate only through reviewed field-level provenance records |
| `src/skywatcher/fpim/aircraft_profile.py` | Exact identity resolver plus observed count/timestamp enrichment; callsign-prefix constants do not populate active identity | Retain; add source adapters without weakening fail-closed activation |
| `scripts/` | Executable adapters importing package-qualified modules | Move remaining reusable logic into packages incrementally |
| `fr24/` | Existing ingest and observable route-processing package | Partition ingestion and analysis in later phases |
| `fr24/rlsm_pipeline.py` and `run-rlsm.sh` | Current-main single-command resumable RLSM workflow | Retain as operator surface |
| `tools/satim_engine/` | Independently distributable SATIM package | Candidate canonical SATIM engine in Phase 2 |
| `tools/satim_route_findings/` | Independently distributable read-only package | Retain |
| Editable `../thehub-pr/packages/*` | Removed from metadata, locks, and workflows | Exact pinned optional packages or future federation workspace |
| `requirements.lock` | Full normalized development/API/federation resolver output | Regenerate only through the pinned CI-equivalent command |
| `Archive/`, `__MACOSX/`, bytecode, caches, build and coverage output | Prohibited by canonical hygiene gate | Never source-controlled or exported |
| Finder-created repository ZIP | Replaced | `skywatcher export-source` deterministic archive |
| Diagnostic API process dictionaries | Encapsulated thread-safe process overlay | Durable or session-scoped review store in a later product phase |

## Compatibility and security rules

1. Existing public analytical schemas remain compatible.
2. Core installation and test collection do not require production data or a sibling TheHub checkout.
3. Federation-enabled installs use exact immutable commit references.
4. The committed lock must equal a fresh normalized resolver output for the declared `dev`, `api`, and `federation` extras.
5. Legacy intent-inference names are excluded from active exports; lazy compatibility access remains warning-emitting and quarantined.
6. Aircraft identifiers resolve by normalized exact match or an explicit alias only.
7. Identity activation is per field. Each active aircraft type, owner, operator, country, or confidence field requires source URI, source record ID, capture time, and SHA-256 provenance.
8. Callsign prefixes do not establish country or any other aircraft identity field. Compatibility prefix tables are excluded from active identity resolution.
9. Ordinary flight-history rows may enrich only observed flight counts and first/last-seen timestamps; they cannot promote identity fields.
10. Mission, purpose, schedule, target, typical operating area, and operational-pattern cueing are never inferred.
11. The CLI requires repository assets for repository validation and fails closed when they are absent or empty.
12. Existing archive destinations are refused by default; explicit replacement is recoverable and failure-path tested.
13. Diagnostic review IDs are server-owned and immutable.
14. Remediation-authored changes do not modify frontend or production-data paths.
15. Current-main governance and RLSM changes remain preserved through a true merge parent.

## Test-tier ownership

| Tier | Purpose |
|---|---|
| Backend core | Clean install, no production data, no TheHub checkout, Python 3.10–3.13, isolated wheel gate, archive/API/FPIM regressions |
| Full-data CI | Repository integration and preserved 55% coverage floor, Python 3.10–3.12 |
| Lock | Full fresh resolution, exact TheHub pin, no sibling editables, byte-for-byte committed-lock comparison |
| Federation contract | Exact-pinned TheHub shared packages and export compatibility |
| Nested tools | Independent SATIM engine and route-findings distributions, including archive rollback parity |
| Security | CodeQL, secret scan, pip-audit, immutable lock validation |
| Desktop | Frozen application smoke and packaging on Ubuntu, macOS, and Windows |
| RLSM | Current-main label-extraction tests and single-command pipeline contract |

## Next migrations

- Phase 1: immutable run manifests, data-pack manifest/doctor, artifact index, cache invalidation, and structured logging.
- Phase 2: select one canonical SATIM engine and convert repository-native runners into adapters.
- Phase 3: full-assets profiling, release automation, generated capability documentation, and gating the existing lint/type backlog.
- Provenance expansion: add reviewed source adapters that emit field-level provenance records; never backfill from callsign structure or unproven history rows.
- Later review-store phase: durable, user/session-scoped review records without weakening the read-only default.

<!-- PHASE0_SYNC_CERTIFICATION_V2 -->
## Current-main synchronization record

Phase 0 was synchronized through true two-parent merge `8dedfcdbdaed34ad6d960e51471c3bf6a957e353` with current `main@9cdf63d584bc58495c32a573dc0fc9ddad981ab8`. The independently reconstructed terminal tree `d498d3aa86992c59997fdbe5eb24355d76c41e91` matched the connector-created tree byte-for-byte. The final code head `035bf9aff9ec4502ea9a79ecc3da74e33a634644` is zero commits behind main and retains 98 net changed files.

The overlap audit covered these 13 paths:

- `.github/workflows/ci.yml`
- `pyproject.toml`
- `fr24/rlsm_unlabeled.py`
- `fr24/satim_engine.py`
- `fr24/satim_engine_core.py`
- `scripts/federation_export.py`
- `scripts/rlsm_geocode_unlabeled.py`
- `scripts/rlsm_ocr_retry_tails.py`
- `src/skywatcher/fpim/aircraft_profile.py`
- `tests/test_aircraft_intelligence.py`
- `tests/test_fr24_todays_batch.py`
- `tests/test_maintenance.py`
- `tools/satim_engine/src/satim_engine/inventory.py`

Adjudication preserved current-main frontend, branding, FOIA canaries, desktop packaging, and server-smoke coverage while retaining Phase 0 CI, packaging, FPIM provenance, regression tests, and archive-security contracts. Ruff modernization was applied without changing public analytical schemas. The resolver-equivalent lock was refreshed from the CI-produced authoritative artifact.
