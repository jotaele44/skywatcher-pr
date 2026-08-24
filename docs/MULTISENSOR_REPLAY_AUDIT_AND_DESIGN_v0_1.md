# Skywatcher multisensor replay — precedent audit and architecture design v0.1

Status: **DRAFT / NON-PRODUCTION DIAGNOSTIC**  
Pinned baseline: `523d61bd858bdbcec5eb8c2df2fd2960c9004404`  
Active vector: `SKYWATCHER_MULTISENSOR_REPLAY`  
Scope: weather radar, satellite, lightning, geomagnetic, seismic, weather-station, screenshot, and existing aircraft observations.

## 1. Executive determination

A provenance-bound multisensor replay capability is feasible within Skywatcher, but no complete replay engine already exists in the repository at the pinned baseline.

The repository does contain substantial reusable precedent:

- timestamped FR24 screenshot and flight-event ingestion;
- SHA-256 source identity, duplicate detection, and availability reconciliation;
- resumable SQLite-backed RLSM processing and immutable operation receipts;
- SATIM layered manifests, per-layer outputs, confidence ledgers, artifact classification, cross-source checks, and GIS overlays;
- JSON Schema-based airspace/export contracts;
- a read-mostly FastAPI federation entity surface;
- a React/Vite diagnostic frontend with Recharts, Radix controls, React Query, and federation client wiring;
- a declared federation boundary in which Skywatcher owns producer logic while TheHub owns the supported product surface.

The correct implementation is therefore an extension of existing provenance, manifest, schema, and review patterns—not a parallel ungoverned application and not a generic conversion of every source into an aircraft observation.

## 2. Precedent inventory

### 2.1 Strong reusable precedent

| Existing capability | Repository precedent | Reuse decision |
|---|---|---|
| Source hashing and duplicate detection | `fr24/screenshot_inventory.py` and RLSM source reconciliation | Reuse SHA-256 identity and fail-closed source-state semantics |
| Timestamped aircraft events | `schemas/flight_event.schema.json`, FR24 ingest scripts, airspace export package | Reuse temporal conventions after explicit UTC normalization review |
| Resumable processing | RLSM SQLite processing runs and source-availability state machine | Reuse run/receipt/accounting pattern, not the screenshot-specific schema |
| Layered sensor-style protocol | `fr24/satim_engine.py`, `fr24/satim_engine_core.py`, SATIM protocol docs | Reuse manifest resolution, per-layer report, provenance, and advisory-layer concepts |
| Artifact taxonomy and adjudication | SATIM artifact classifier, confidence ledger, review paths | Reuse machine-versus-human adjudication separation |
| GIS alignment | `gis_intelligence.py`, SATIM GIS overlay and geometry modules | Reuse spatial validation helpers; add explicit raster CRS/grid contracts |
| Export validation | `schemas/airspace_observation.schema.json`, export manifest validators | Reuse validator conventions; create separate sensor contracts |
| Read API | `server/backend/main.py` entity contract | Extend with bounded replay read endpoints; do not force binary frames into generic entity rows |
| Diagnostic UI | React/Vite frontend; Recharts; Radix Slider/Tabs/Switch | Reuse controls and charts; add a map/raster dependency only after review |
| Federation governance | README and `frontend/README.md` | Preserve Skywatcher producer ownership and TheHub product-surface authority |

### 2.2 Partial or misleading precedent

| Candidate precedent | Limitation |
|---|---|
| FR24 screenshot sequence | Provides visual chronology, but not queryable radar or aircraft telemetry unless independently extracted |
| SATIM layers | Calibration/evidence layers are not a general replay clock and must not be renamed into one |
| FastAPI entity loader | Optimized for committed JSONL/CSV artifacts; not suitable for large georeferenced raster payloads |
| In-memory frontend review overlay | Process-scoped and non-durable; cannot serve as authoritative sensor adjudication storage |
| Existing “timeline” references | Operational/analytical timelines, not deterministic multi-stream playback |

### 2.3 No complete precedent found

No pinned-baseline implementation was found that already provides all of the following:

- a deterministic common replay clock;
- synchronized vector, raster, time-series, and screenshot streams;
- frame stepping and bounded speed control;
- explicit missing intervals and clock-quality flags;
- immutable replay receipts;
- radar-specific product metadata and artifact adjudication;
- end-to-end Skywatcher API/client/component and TheHub route reachability.

## 3. Architectural invariants

1. **Sensor types remain distinct.** Radar reflectivity is not an aircraft track; geomagnetic variation is not a radar return.
2. **UTC is canonical.** Original timezone text, offset, precision, and conversion evidence are retained.
3. **No silent interpolation.** Missing observations remain visible. Interpolation is disabled by default and, when enabled for an eligible vector stream, is labeled and reproducible.
4. **Source bytes are immutable evidence.** Normalized derivatives never replace the acquired source.
5. **Every replay is content-bound.** A replay receipt binds source manifests, normalized members, parameters, software version, and output digest.
6. **Machine inference is not human adjudication.** Both are stored separately with actor/method/version and timestamps.
7. **No causal claims from temporal coincidence.** Correlation windows are navigational aids, not evidence that one sensor phenomenon caused another.
8. **Licensing is fail-closed.** Provider-rendered tiles or screenshots cannot be redistributed unless the source terms permit it.
9. **TheHub authority is preserved.** Skywatcher may expose a diagnostic replay view, but the supported federation UI belongs in TheHub.
10. **Production promotion requires real, licensed fixtures.** Synthetic fixtures may test behavior but cannot certify live data availability.

## 4. Canonical domain model

### 4.1 Sensor source

A stable source registry entry:

```json
{
  "source_id": "usgs-sjg-geomagnetic",
  "sensor_family": "geomagnetic",
  "provider": "USGS",
  "product_types": ["x_nT", "y_nT", "z_nT", "f_nT"],
  "license_or_terms_ref": "...",
  "native_timezone": "UTC",
  "spatial_footprint": {"type": "Point", "coordinates": [-66.15, 18.11]},
  "enabled": false
}
```

### 4.2 Observation envelope

Required common fields:

```text
observation_id
source_id
sensor_family
product_type
event_time_utc
source_time_text
source_timezone
source_time_precision
clock_quality
observed_geometry
bbox
crs
quality_flags
source_member_sha256
normalization_version
ingested_at_utc
```

The envelope carries only common metadata. Payloads remain type-specific.

### 4.3 Payload families

| Payload family | Examples | Recommended storage |
|---|---|---|
| Vector event | aircraft positions, lightning, seismic event points | Parquet/JSONL for packages; indexed SQL for runtime |
| Time series | magnetic components, pressure, wind, infrasound | Parquet/Arrow or chunked CSV fixtures; indexed metadata in SQL |
| Raster frame | reflectivity, satellite imagery, accumulation | GeoTIFF/COG or licensed local source object; metadata index in SQL |
| Provider-rendered frame | Windy/FR24 screenshots | Original image plus sidecar georeference/time metadata |
| Waveform/spectral | seismic waveform, acoustic, range-Doppler | Binary/array object plus manifest; no generic JSON embedding |

### 4.4 Replay session

A replay session is a deterministic query, not a mutable media project:

```text
replay_id
window_start_utc
window_end_utc
clock_step_ms
playback_rate
selected_source_ids
selected_product_types
spatial_filter
interpolation_policy
frame_selection_policy
gap_policy
source_manifest_digest
software_revision
```

### 4.5 Replay receipt

The terminal receipt must include:

- canonical replay request digest;
- exact repository revision;
- source and normalized manifest digests;
- selected/omitted/invalid member counts by source;
- first and last event timestamps;
- explicit gap intervals;
- interpolation count by source and method;
- frame and event accounting totals;
- deterministic output digest;
- warnings and blockers;
- terminal status: `completed`, `blocked`, or `failed`.

## 5. Proposed repository layout

```text
sensor_replay/
  __init__.py
  clock.py
  manifests.py
  models.py
  normalization.py
  quality.py
  receipts.py
  storage.py
  adapters/
    fr24.py
    provider_frame.py
    geomagnetic.py
    weather_station.py
    weather_radar.py
    satellite.py
    lightning.py
    seismic.py

schemas/
  sensor_source_v1.schema.json
  sensor_observation_v1.schema.json
  sensor_frame_manifest_v1.schema.json
  replay_session_v1.schema.json
  replay_receipt_v1.schema.json
  sensor_adjudication_v1.schema.json

scripts/
  build_sensor_manifest.py
  validate_sensor_package.py
  build_replay_receipt.py

server/backend/
  replay.py

frontend/src/
  pages/MultisensorReplay.jsx
  components/replay/
  api/replayClient.js

tests/
  fixtures/multisensor_replay_v1/
  test_sensor_schemas.py
  test_replay_clock.py
  test_replay_accounting.py
  test_replay_api.py
  test_replay_gui_contract.py
```

The exact frontend paths must follow the current route/component conventions during implementation rather than being created blindly from this design.

## 6. Storage boundaries

### 6.1 Repository

Allowed:

- schemas;
- source registries without secrets;
- small synthetic or redistribution-safe fixtures;
- normalized test manifests;
- expected deterministic receipts.

Disallowed:

- provider credentials;
- bulk proprietary radar tiles;
- large operational time series;
- unlicensed screenshots or video archives;
- mutable runtime databases.

### 6.2 Runtime data root

Use a configurable root outside Git:

```text
SKYWATCHER_SENSOR_DATA_ROOT/
  sources/<source_id>/<acquisition_id>/
  normalized/<source_id>/<normalization_id>/
  indexes/
  replay_receipts/<replay_id>/
  cache/
```

All paths in manifests are relative to the declared data root. Lexical traversal, symlink retargeting, duplicate resolved targets, and source/control namespace overlap must fail closed, consistent with RLSM hardening precedent.

### 6.3 Database

SQLite is acceptable for a bounded diagnostic implementation. PostgreSQL/PostGIS or a dedicated time-series store may be required later, but should not be introduced before measured scale warrants it.

Do not put large raster or waveform bytes in ordinary relational rows. Store references, hashes, dimensions, CRS, time bounds, quality, and availability state.

## 7. Deterministic replay clock

### 7.1 Clock semantics

- Canonical monotonic replay cursor expressed as UTC milliseconds.
- Events become visible when `event_time_utc <= cursor` according to the selected frame policy.
- Raster frame selection defaults to latest valid frame at or before cursor within a source-specific maximum age.
- Time-series displays only measured samples unless an explicitly selected rendering method connects points visually.
- Clock rate changes presentation speed only; they do not alter event ordering.
- Frame step advances to the next union timestamp across enabled sources, with deterministic tie ordering by source ID and observation ID.

### 7.2 Gap policy

A gap is emitted when any required source has no valid sample/frame in its declared expected interval. Gaps are first-class records with:

```text
source_id
start_utc
end_utc
reason
expected_cadence
last_valid_observation_id
next_valid_observation_id
```

The GUI must show gaps rather than freezing a stale layer without indication.

### 7.3 Interpolation policy

Default: `none`.

Initially eligible only for aircraft/vector tracks and scalar chart rendering. Never interpolate:

- radar raster pixels;
- lightning detections;
- seismic event existence;
- artifact classifications;
- missing provider-rendered screenshots.

## 8. Initial adapter contracts

### 8.1 FR24 observations

Reuse existing event/screenshot identities. Adapter responsibilities:

- normalize timestamp and preserve original timestamp text;
- map existing event geometry to the common envelope;
- retain screenshot/source binding;
- expose extraction confidence and source availability;
- avoid upgrading inferred tracks into measured positions.

### 8.2 Provider-rendered radar frames

This is the correct initial path for examples such as the Windy Mexico frame.

Required metadata:

- provider/application;
- displayed product label;
- capture time and timezone certainty;
- image SHA-256;
- viewport/bounds or georeferencing method;
- source attribution and redistribution status;
- `raw_radar_data=false`;
- classification state and uncertainty.

A provider-rendered frame must never be labeled Level II/III, radial velocity, or station-native reflectivity without evidence.

### 8.3 USGS SJG geomagnetic series

Adapter must preserve measured components, units, cadence, quality flags, station metadata, source URL/receipt, and gaps. Derived anomaly scores must live in a separate analysis record and cannot overwrite measured values.

### 8.4 Weather context

Use authoritative station or gridded observations with explicit product identity. Forecasts must not be mixed into an observation replay unless clearly separated as forecast issue/valid times.

## 9. Weather-radar artifact taxonomy

Allowed machine labels:

```text
meteorological_echo
ground_clutter
anomalous_propagation
rf_interference
scan_sector_failure
range_gate_corruption
mosaic_error
georeferencing_error
raster_tile_error
client_rendering_error
unresolved
```

Required adjudication fields:

```text
classification
classification_source: machine | human
method_or_model
method_version
confidence
supporting_observation_ids
contradicting_observation_ids
adjudicated_at_utc
adjudicator
notes
```

No label may assert geomagnetic causation solely because a magnetic excursion occurs in the same replay window.

## 10. API design

The current generic entity API remains intact. Add bounded read-only replay endpoints:

```text
GET  /api/replay/sources
POST /api/replay/query
GET  /api/replay/{replay_id}/manifest
GET  /api/replay/{replay_id}/events
GET  /api/replay/{replay_id}/series/{source_id}
GET  /api/replay/{replay_id}/frames/{source_id}/{frame_id}
GET  /api/replay/{replay_id}/receipt
```

`POST /query` is a read operation over a bounded request. It must enforce maximum window, source count, and returned event limits.

Binary delivery must validate that the requested member is present in the bound manifest and that its current SHA-256 matches. The endpoint must not accept arbitrary filesystem paths.

## 11. GUI design and federation parity

### 11.1 Skywatcher diagnostic surface

Required controls:

- UTC timeline scrubber;
- play/pause and next/previous union timestamp;
- bounded playback rates;
- source and product toggles;
- map/vector/raster viewport;
- synchronized scalar charts;
- explicit stale-layer and gap indicators;
- provenance drawer;
- artifact classification/review panel;
- export replay receipt action.

The current dependency set already supports charts and controls. A map/raster library is not confirmed in the pinned package manifest and must be selected only after reviewing existing components and TheHub compatibility.

### 11.2 TheHub product surface

Production completeness requires the same capability to be reachable through:

```text
Skywatcher producer
  -> validated replay package/API
  -> federation client
  -> TheHub route
  -> TheHub page/component
  -> discoverable navigation
  -> end-to-end test
```

A working diagnostic route in Skywatcher alone is insufficient.

## 12. Validation ladder

### Gate A — Structural

- schemas compile and reject unknown/invalid sensor-family payloads;
- UTC timestamps require offsets and canonical normalization;
- all binary members are SHA-bound;
- path isolation and traversal tests pass;
- no secrets or external network access in fixtures.

### Gate B — Determinism

Run the same bounded fixture twice:

- identical canonical replay request digest;
- identical source selection and omission accounting;
- identical union timestamp sequence;
- identical gap ledger;
- identical replay receipt bytes and SHA-256;
- 100% input-member accounting.

Volatile invocation timestamps must not enter the deterministic content section. They may exist in a non-authoritative execution envelope.

### Gate C — Semantic separation

Tests must prove:

- radar frames do not become aircraft observations;
- geomagnetic values do not become radar intensities;
- source screenshots remain marked provider-rendered;
- machine and human classifications cannot overwrite each other;
- interpolation is absent unless explicitly enabled;
- causal language is not generated from co-occurrence alone.

### Gate D — API

- bounded time and result limits;
- no arbitrary file access;
- correct MIME type and digest validation;
- explicit 404/409/422 states for missing, replaced, or invalid members;
- gap and stale-source metadata delivered to clients.

### Gate E — GUI parity

- backend-to-client-to-component reachability;
- visible controls for every supported replay function;
- keyboard access and focus behavior;
- no hidden terminal-only requirement for ordinary replay;
- Skywatcher diagnostic and TheHub product routes tested separately.

### Gate F — Live-source admission

For each source:

- license/terms reviewed;
- source identity and endpoint pinned where possible;
- bounded acquisition receipt;
- schema and semantic validation;
- outage behavior tested;
- redistribution status explicit;
- no production promotion from synthetic-only evidence.

## 13. Bounded implementation sequence

### Phase 0 — Contracts and deterministic core

Implement common schemas, manifest validation, source registry, replay clock, gap ledger, receipts, and a synthetic multisensor fixture.

### Phase 1 — Existing-data adapters

Add FR24 observation and provider-rendered-frame adapters. These use data forms already represented in Skywatcher and carry the lowest external-dependency risk.

### Phase 2 — Time-series pilot

Add a geomagnetic fixture shaped like SJG data and a weather-station fixture. Live acquisition remains disabled until terms and endpoint behavior are separately certified.

### Phase 3 — Diagnostic API and GUI

Expose bounded replay queries and the Skywatcher diagnostic page. No persistent review writes until an authoritative adjudication store is designed.

### Phase 4 — Native scientific products

Add licensed weather-radar, satellite, lightning, and seismic adapters one source at a time. Each adapter requires its own admission receipt and fixture.

### Phase 5 — TheHub integration

Implement the supported federation route, navigation, capability manifest entry, API/client/component parity tests, and end-to-end GUI validation.

## 14. Risks and blockers

| Risk | Current state | Required control |
|---|---|---|
| Exact map library | Not established | Inventory current frontend/TheHub mapping stack before implementation |
| Durable runtime DB | Not established for replay | Start with bounded SQLite index; prohibit in-memory adjudication authority |
| Provider licenses | Unknown per source | Source admission ledger and redistribution flag |
| Raw Mexican radar archive | Not available in repo | Treat supplied imagery only as provider-rendered evidence |
| Timezone ambiguity | Common in screenshots | Preserve source text and uncertainty; no guessed UTC |
| Clock drift | Unmeasured across sources | Clock-quality and offset metadata; no false precision |
| Raster volume | Potentially large | External data root, COG/tiles, bounded cache |
| False correlation | High analytic risk | Neutral UI language and separate correlation/causation fields |
| TheHub parity | Not implemented | Required before supported product status |
| Network-dependent tests | Unreliable | Hermetic fixtures for CI; bounded operator receipts for live checks |

## 15. Decision

Proceed with a **native Skywatcher multisensor replay foundation**, using existing RLSM/SATIM provenance and deterministic-processing precedent while keeping sensor payloads separate.

Do not adopt Open MCT or another runtime as a dependency in this phase. Such systems may be evaluated later against the established contracts; they are not required to prove the core capability.

## 16. Acceptance criteria for the first implementation PR

The first implementation PR is complete only when it provides:

1. versioned source, observation, replay-session, replay-receipt, and adjudication schemas;
2. a deterministic replay clock with union-timestamp stepping;
3. explicit gap accounting and `none` interpolation default;
4. FR24 and provider-rendered-frame adapters;
5. synthetic geomagnetic and weather time-series adapters;
6. a redistribution-safe bounded fixture;
7. two-run byte-identical authoritative receipts;
8. 100% fixture member accounting;
9. tests for type separation, timestamp handling, path safety, and content replacement;
10. no credentials, external downloads, live claims, or TheHub production-status change.

The diagnostic GUI and TheHub wiring should follow as separately reviewable phases unless the exact integrated change can be validated atomically without broadening the failure surface.
