# skywatcher-pr — Airspace Intelligence Producer (PRII federation)

The **airspace / aircraft-intelligence** node of the Puerto Rico Integrated Intelligence
(PRII) federation. Skywatcher turns FlightRadar24 tracks/screenshots and aircraft-registry
data into airspace observations, links them to PR infrastructure, and exports them for the
federation Hub ([thehub-pr](https://github.com/jotaele44/thehub-pr)).

> Skywatcher maps aircraft activity, missions, and airspace–infrastructure relationships.
> It does not allege wrongdoing.

## Engine (pure-Python core)

| Module | Role |
|--------|------|
| `aircraft_intelligence.py` | Callsign → aircraft profile lookup, operator/mission inference, intelligence reports |
| `ilap_airspace_bridge.py` | ILAP (Infrastructure-Linked Airspace Profile) bridge: links flights to PR infrastructure (uses `gis_intelligence`) |
| `aasb_airspace_bridge.py` | Airspace–Asset Spatial Bridge |
| `prii_readiness_engine.py` | Operational readiness scoring/reporting |
| `gis_intelligence.py` | PR infrastructure model + geodesy helpers (`haversine_nm`) |

The core has **no third-party dependencies** (stdlib + sqlite3). Run the suite with `pytest`.

### Optional GEBCO terrain layer

`gebco/` (bathymetry/terrain analysis — Mona Passage profiles, underwater ridges) needs the
heavy geospatial stack and is opt-in:

```bash
pip install -r requirements-geo.txt   # numpy / scipy / xarray / netCDF4
```

Its tests self-skip when those packages are absent.

## FR24 ingest subsystem (migrated from spiderweb-pr)

The FlightRadar24 screenshot-processing pipeline that turns raw FR24 captures into
airspace observations now lives in-tree under `fr24/` (38 stdlib-only modules — no
torch/opencv/paddleocr):

| Module | Role |
|--------|------|
| `fr24/screenshot_inventory.py` | Directory scan, SHA-256 hashing, corrupt/duplicate detection |
| `fr24/ui_segmenter.py` | Segments the FR24 UI into map/panel/label regions |
| `fr24/route_extractor.py` | HSV masking + BFS to extract route polylines |
| `fr24/manual_review_queue.py` | SQLite-backed queue for low-quality items |
| `fr24/event_export.py` | inventory → `screenshots` table; routes → `track_points` table |

Drive the pipeline with `scripts/fr24_vision_ingest.py`. Coverage is `tests/test_fr24_*`,
`test_rlsm_*`, `test_route_extractor`, `test_manual_review_queue` (stdlib-only, runs under
the default `pytest -q`).

## Federation export contract

Skywatcher emits **airspace observation packages** validated by
`scripts/validate_airspace_export.py` against `schemas/airspace_observation.schema.json` and
`schemas/airspace_export_manifest.schema.json`. A synthetic example lives in
`exports/examples/synthetic_airspace_package/`.

```bash
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode test
python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode production  # rejects synthetic rows
```

See [`docs/AIRSPACE_PRODUCER_EXPORT_TARGET.md`](docs/AIRSPACE_PRODUCER_EXPORT_TARGET.md) and the
node's [`federation.json`](federation.json).

## Provenance

- **Engine** extracted from `spiderweb-pr` branch `claude/pr-airspace-intelligence-v7Mbh`
  (final-gap-closure airspace implementation), keeping the flat-module layout it was built in.
- **Export contract** salvaged from `Puerto-Rico-Airspace-Intelligence-Tool` PR #1 before that
  repo's retirement.

Deferred follow-ups (still in the spiderweb archive branch): GEBCO wiring into ILAP,
RAG/earthgpt context, satellite ingest, and the mission/operational-intelligence modules.

## Develop

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```
