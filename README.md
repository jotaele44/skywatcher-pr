# skywatcher-pr — Airspace Evidence Producer (PRII federation)

`skywatcher-pr` is the airspace and aircraft-activity evidence producer for the Puerto Rico Integrated Intelligence (PRII) federation. It owns FlightRadar24 screenshot and track ingestion, airspace-observation generation, provenance-gated aircraft-identity enrichment, SATIM imagery calibration, and federation export packages for [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

> Skywatcher records observable aircraft activity and source-declared metadata. It does **not** infer mission, intent, target, wrongdoing, causality, or operational purpose, and it does not provide operational cueing.

> Aircraft identity fields are promoted only when that individual field has a source URI, source record ID, capture time, and SHA-256. Legacy registry membership and ordinary flight-history rows prove nothing beyond observed identifiers and timestamps; unproven identity fields remain `Unknown`.

> Callsign prefixes are not aircraft-country evidence. Compatibility prefix tables are not consulted by active identity resolution, and `country` remains `Unknown` unless complete field-level provenance activates it.

> **Diagnostic-only surface.** The repository dashboard is a development and diagnostic surface for this producer. The supported federation product surface is the hub application in `thehub-pr`.

## Federation role

| Field | Value |
|---|---|
| Program ID | `skywatcher-pr` |
| Federation role | `airspace_intelligence_node` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Active vector | `SKYWATCHER_AIRSPACE_AIRCRAFT_INTELLIGENCE` |
| Production status | `NON_PRODUCTION_DIAGNOSTIC` |
| Operational cueing | `false` |
| Intent inference | prohibited |
| Live execution | blocked pending real captures and a production export |

Skywatcher is the active owner of the FR24 pipeline migrated from `spiderweb-pr`. Spiderweb may retain spatial bridge/reference material, but FR24 ingestion and active airspace-observation export belong here.

## Architecture

The repository uses a PEP 517 `src/` package while preserving existing root import paths through compatibility facades.

| Surface | Role |
|---|---|
| `src/skywatcher/core/` | Shared contracts, normalization, provenance-gated registries, readiness, repository policy, source export, archive safety |
| `src/skywatcher/satim/`, `fr24/calibration/` | Terrain/imagery calibration and artifact assessment |
| `src/skywatcher/fpim/`, `fr24/` | Exact aircraft identity and observed flight-path/behavior processing |
| `src/skywatcher/corrim/`, `src/skywatcher/fusion/` | Evidence correlation without intent or causality inference |
| `src/skywatcher/federation/` | Federation compatibility helpers |
| `server/backend/` | Read-mostly diagnostic API; mutations are disabled by default and remain process-scoped |
| `tools/satim_engine/` | Distributable SATIM engine package |
| `tools/satim_route_findings/` | Read-only SATIM route-findings package |

Legacy `FlightMissionAnalyzer` compatibility symbols are quarantined under `skywatcher.legacy`, excluded from the active API, and emit deprecation warnings when accessed through the old facade. Active profiles never expose inferred missions, typical operating hours, or high-activity-region cueing.

## Install

Core development does not require a sibling checkout:

```bash
python -m pip install -e ".[dev,api]"
skywatcher --root "$PWD" doctor
skywatcher --root "$PWD" validate
pytest
```

Federation packages are optional and pinned to an exact `thehub-pr` commit:

```bash
python -m pip install -e ".[federation]"
```

Other optional stacks:

```bash
python -m pip install -e ".[geo]"
python -m pip install -e ".[imagery]"
python -m pip install -e ".[desktop,federation]"
```

`requirements.lock` is generated from the declared development, API, and federation extras. CI performs the same pinned `uv pip compile`, rejects editable sibling paths, verifies the exact TheHub SHA, and requires the committed lock to match the fresh resolver output byte-for-byte.

## Unified CLI

```text
skywatcher --root <repo> doctor
skywatcher --root <repo> validate
skywatcher --root <repo> export-source dist/skywatcher-source.zip
```

- `doctor` reports dependency, executable, data-pack, repository-asset, runtime-write, and policy capability states.
- `validate` compiles every JSON Schema under `<repo>/schemas`; it fails when the schema directory is absent or empty.
- `export-source` creates a deterministic tracked-source archive that excludes frontend, production data, generated outputs, caches, build products, coverage products, and runtime reports while preserving executable launcher modes.

An installed wheel does not silently treat the current directory as a valid repository. CI installs the wheel in a clean virtual environment, changes to an empty directory, verifies rootless validation fails, and then validates the repository through explicit `--root`.

## FR24 ingest

The FlightRadar24 screenshot-processing pipeline lives in `fr24/`.

| Module | Role |
|---|---|
| `fr24/screenshot_inventory.py` | Directory scan, SHA-256 hashing, corrupt/duplicate detection |
| `fr24/ui_segmenter.py` | FR24 UI segmentation |
| `fr24/route_extractor.py` | Observable route-polyline extraction |
| `fr24/manual_review_queue.py` | SQLite-backed low-quality review queue |
| `fr24/event_export.py` | Inventory/route conversion into observation tables |

```bash
python scripts/fr24_vision_ingest.py
```

### RLSM screenshot extraction

The screenshot corpus—OCR, aircraft fields, place labels, map icons, geocoding, review queues, exports, and reports—runs through one resumable command:

```bash
./run-rlsm.sh              # full pipeline; use --dry-run for preflight only
./run-rlsm.sh --status     # report completed and pending stages
```

Point `data/FR24_baseline` at the machine-local corpus first. A symlink is supported, and preflight prints the required command when the path is absent. The full operator runbook is `data/rlsm/HANDOFF.md`.

## SATIM protocol

Repository-native protocol runner:

```bash
python -m fr24.satim_engine run \
  --manifest path/to/satim_manifest.yaml \
  --output reports/satim/runs/<run_id>
```

Autodetect mode accepts a directory or ZIP:

```bash
python -m fr24.satim_engine run \
  --input path/to/input_dir_or_zip \
  --output reports/satim/runs/<run_id>
```

ZIP inputs use the same safety contract in the repository-native and independently distributable engines. The contract rejects traversal, aliases, Windows reserved names, alternate-data-stream syntax, symlinks, encrypted members, duplicates, excessive size, and excessive compression. Existing targets are refused by default; explicit replacement uses a backup-and-rollback promotion sequence whose failure path is regression-tested in both distributions.

The standalone distributable engine remains under `tools/satim_engine/` and exposes the `satim` command.

## Federation export contract

Skywatcher emits airspace-observation packages validated against:

```text
schemas/airspace_observation.schema.json
schemas/airspace_export_manifest.schema.json
```

```bash
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode test
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode production
```

Production mode rejects synthetic rows. `ready_for_hub_live_execution` remains false until non-synthetic inputs are supplied and a production export passes.

## Test tiers

The test system separates reproducible core operation from full-repository coverage:

```bash
# Data-independent default
pytest

# Full-data tier used by the coverage workflow
PYTEST_ADDOPTS="" pytest -m "not integration and not requires_thehub"

# Explicit capability tiers
pytest -m requires_data
pytest -m requires_thehub
pytest tools/satim_engine/tests
pytest tools/satim_route_findings/tests
```

- `Backend core` installs the project cleanly, validates repository hygiene and schemas, runs the data-independent suite across Python 3.10–3.13, builds the wheel, performs the isolated install gate, and runs both nested tool suites.
- `Skywatcher CI` runs the full-data suite across Python 3.10–3.12 and retains the 55% coverage floor.
- Current-main security controls include CodeQL, secret scanning, pip-audit, resolver-equivalent lock validation, Dependabot, pinned Actions, frontend lint/build, and report-visible Ruff/mypy.
- Desktop builds and frozen-app smoke tests run on Ubuntu, macOS, and Windows.

## Diagnostic API write policy

The API is read-only by default. Mutations require both:

```text
PRII_ENABLE_WRITES=true
PRII_WRITE_TOKEN=<non-empty token>
```

Every mutating request must send `Authorization: Bearer <token>`. Local-network location alone never grants write access. The server owns entity IDs, rejects ID and internal-overlay fields in payloads, limits payload size and field count, and keeps changes process-scoped without mutating repository files.

The public-settings endpoint reports whether a write token is required so preserved current-main frontend tooling can prompt for the token without storing it in the generic application-parameter namespace.

## Runtime and source hygiene

Generated content belongs outside source control under a runtime workspace such as `var/`. CI rejects archive copies, macOS resource forks, interpreter bytecode, caches, local databases, build and wheel products, coverage products, generated maintenance reports, and runtime exports. The source exporter and hygiene scanner share one canonical policy.

Use `skywatcher --root <repo> export-source ...` rather than Finder-created ZIP files for repository handoffs.

## Phase 0 review evidence

- `docs/PHASE_0_CHANGE_LEDGER.md`
- `docs/PHASE_0_TEST_EVIDENCE.md`
- `docs/PHASE_0_MIGRATION_MAP.md`
- `docs/PHASE_0_REMEDIATION_LEDGER.md`
- `docs/PHASE_0_REVIEW_CLOSURE.md`

## Provenance

- Engine extracted from the Spiderweb airspace implementation branch.
- FR24 ingest migrated from `spiderweb-pr` into `fr24/`.
- Export contract salvaged from the retired airspace tooling path.
- Phase 0 hardening preserves analytical and schema compatibility while establishing reproducible packaging, immutable dependency resolution, recoverable archive handling, field-provenance-gated identity enrichment, API identity security, and continuous security gates.

<!-- PHASE0_SYNC_CERTIFICATION_V2 -->
## Current Phase 0 synchronization certification

The authoritative synchronized code head is `035bf9aff9ec4502ea9a79ecc3da74e33a634644`. It descends from true two-parent merge `8dedfcdbdaed34ad6d960e51471c3bf6a957e353`, whose ordered parents are Phase 0 head `1bfaea7c37ff42d0614934b0553cf8aacad9bfcc` and current `main@9cdf63d584bc58495c32a573dc0fc9ddad981ab8`. The independently reconstructed and connector-verified merge tree is `d498d3aa86992c59997fdbe5eb24355d76c41e91`.

- Pull request #110 is open, draft, mergeable, unmerged, and zero commits behind current main.
- The pull-request diff remains **98 files**.
- Current-main frontend, branding, FOIA canary workflows, desktop packaging, and `tests/test_server_smoke.py` are preserved.
- Net differences relative to current main under `frontend/` and production `data/` are zero.
- Field-level aircraft provenance remains fail-closed; callsign prefixes and ordinary flight-history rows cannot promote identity.
- Role, mission, purpose, target, schedule, typical operating area, and operational cueing remain unresolved or absent.
- Core and standalone SATIM archive implementations retain matching validation, bounded extraction, replacement rollback, and frozen-default behavior.
- `requirements.lock` equals the authoritative normalized resolver output; exact TheHub references remain pinned at `f00f2da0e6abcc885a8133e5c8b7aeb9756f5df8`.
- All eleven workflow families succeeded on the synchronized code head. The exact run ledger is in `docs/PHASE_0_TEST_EVIDENCE.md`.

This certification does not authorize merge or a ready-for-review transition.
