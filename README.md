# skywatcher-pr — Airspace Evidence Producer (PRII federation)

`skywatcher-pr` is the airspace and aircraft-activity evidence producer for the Puerto Rico Integrated Intelligence (PRII) federation. It owns FlightRadar24 screenshot and track ingestion, airspace-observation generation, source-declared aircraft-profile enrichment, SATIM imagery calibration, and federation export packages for [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

> Skywatcher records observable aircraft activity and source-declared metadata. It does **not** infer mission, intent, target, wrongdoing, or operational purpose, and it does not provide operational cueing.

> **Diagnostic-only surface (ADR 0001, Phase 2).** The repository dashboard is a development and diagnostic surface for this producer. The supported federation product surface is the hub application in `thehub-pr`.

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

Skywatcher is the active owner of the FR24 pipeline migrated from `spiderweb-pr`. Spiderweb may retain spatial bridge/reference material, but FR24 ingestion and active airspace-observation export belong here.

## Architecture

The repository uses a PEP 517 `src/` package while preserving existing root import paths through compatibility facades.

| Surface | Role |
|---|---|
| `src/skywatcher/core/` | Shared contracts, registries, normalization, readiness, archive safety |
| `src/skywatcher/satim/`, `fr24/calibration/` | Terrain/imagery calibration and artifact assessment |
| `src/skywatcher/fpim/`, `fr24/` | Aircraft identity and observed flight-path/behavior processing |
| `src/skywatcher/corrim/`, `src/skywatcher/fusion/` | Evidence correlation without intent or causality inference |
| `src/skywatcher/federation/` | Federation compatibility helpers |
| `server/backend/` | Read-mostly diagnostic API; mutations are disabled by default |
| `tools/satim_engine/` | Distributable SATIM engine package |
| `tools/satim_route_findings/` | Read-only SATIM route-findings package |

Legacy `FlightMissionAnalyzer` compatibility symbols are quarantined under `skywatcher.legacy`, excluded from the active API, and emit deprecation warnings when accessed through the old facade.

## Install

Core development does not require a sibling checkout:

```bash
python -m pip install -e ".[dev,api]"
skywatcher doctor
skywatcher validate
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

## Unified CLI

```text
skywatcher doctor
skywatcher validate
skywatcher export-source dist/skywatcher-source.zip
```

- `doctor` reports package, executable, data-pack, and policy capability states.
- `validate` compiles every JSON Schema under `schemas/`.
- `export-source` creates a deterministic tracked-source archive that excludes `frontend/`, `data/`, runtime outputs, caches, and generated exports.

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

ZIP inputs are extracted through bounded, traversal-resistant archive handling. The standalone distributable engine remains under `tools/satim_engine/` and exposes the `satim` command.

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

The default suite excludes capabilities that require omitted production data, external services, sibling federation packages, optional geospatial dependencies, or external OCR executables.

```bash
pytest
pytest -m requires_data
pytest -m requires_thehub
pytest tools/satim_engine/tests
pytest tools/satim_route_findings/tests
```

The backend-core workflow installs the project in a clean environment, validates repository hygiene and schemas, runs the data-independent suite across Python 3.10–3.13, builds a wheel, smoke-installs it, and runs both nested tool suites.

## Diagnostic API write policy

The API is read-only by default. Mutations require both:

```text
PRII_ENABLE_WRITES=true
PRII_WRITE_TOKEN=<non-empty token>
```

Every mutating request must then send `Authorization: Bearer <token>`. Local-network location alone never grants write access. Changes remain process-scoped and are not persisted to repository files.

## Runtime and source hygiene

Generated content belongs outside source control under a runtime workspace such as `var/`. CI rejects archive copies, macOS resource forks, interpreter bytecode, caches, local databases, and generated runtime exports. Use `skywatcher export-source` rather than Finder-created ZIP files for repository handoffs.

## Provenance

- Engine extracted from the Spiderweb airspace implementation branch.
- FR24 ingest migrated from `spiderweb-pr` into `fr24/`.
- Export contract salvaged from the retired airspace tooling path.
- Phase 0 hardening preserves analytical behavior and schema compatibility while establishing reproducible packaging and security gates.
