# skywatcher-pr — Airspace Intelligence Producer (PRII federation)

`skywatcher-pr` is the **airspace / aircraft-intelligence producer** for the Puerto Rico Integrated Intelligence (PRII) federation. It owns FlightRadar24 screenshot/track ingestion, airspace observation generation, aircraft-intelligence enrichment, and airspace export packages for [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

> Skywatcher maps aircraft activity, missions, and airspace-infrastructure relationships. It does not allege wrongdoing.

## Federation role

| Field | Value |
|---|---|
| Program id | `skywatcher-pr` |
| Federation role | `airspace_intelligence_node` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Active vector | `SKYWATCHER_AIRSPACE_AIRCRAFT_INTELLIGENCE` |
| Production status | `NON_PRODUCTION_DIAGNOSTIC` |

Skywatcher is the active owner of the FR24 pipeline migrated out of `spiderweb-pr`. Spiderweb may retain spatial bridge/reference material, but FR24 ingestion and active airspace observation export belong here.

## Engine

| Module | Role |
|---|---|
| `aircraft_intelligence.py` | Callsign to aircraft profile lookup, operator/mission inference, reports |
| `ilap_airspace_bridge.py` | Infrastructure-Linked Airspace Profile bridge |
| `aasb_airspace_bridge.py` | Airspace-Asset Spatial Bridge |
| `prii_readiness_engine.py` | Operational readiness scoring/reporting |
| `gis_intelligence.py` | Puerto Rico infrastructure model and geodesy helpers |
| `fr24/` | FR24 screenshot inventory, segmentation, route extraction, review queue, event export |

The core is designed to run with stdlib-first dependencies. Optional geospatial layers are isolated behind separate requirements.

## FR24 ingest subsystem

The migrated FlightRadar24 screenshot-processing pipeline lives in `fr24/`.

| Module | Role |
|---|---|
| `fr24/screenshot_inventory.py` | Directory scan, SHA-256 hashing, corrupt/duplicate detection |
| `fr24/ui_segmenter.py` | Segments FR24 UI regions |
| `fr24/route_extractor.py` | Extracts route polylines |
| `fr24/manual_review_queue.py` | SQLite-backed queue for low-quality items |
| `fr24/event_export.py` | Converts inventory/routes into observation tables |

Drive the pipeline with:

```bash
python scripts/fr24_vision_ingest.py
```

## Federation export contract

Skywatcher emits airspace observation packages validated against:

```text
schemas/airspace_observation.schema.json
schemas/airspace_export_manifest.schema.json
```

Synthetic package validation:

```bash
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode test
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode production
```

Production-mode validation rejects synthetic rows. Current live-execution blockers should remain explicit until non-synthetic observations are loaded and exported.

## Optional GEBCO terrain layer

```bash
pip install -r requirements-geo.txt
```

`gebco/` is optional and tests should self-skip when geospatial dependencies are absent.

## Develop

```bash
python -m pip install -r requirements-dev.txt
pytest -q
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode test
```

## Provenance

- Engine extracted from the Spiderweb airspace implementation branch.
- FR24 ingest migrated from `spiderweb-pr` into `fr24/`.
- Export contract salvaged from the retired airspace tooling path.
