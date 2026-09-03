
# ADR-0002: Interactive Airspace Console Architecture

- **Status:** Accepted for phased implementation; Phase 1 and Phase 2 are in draft review
- **Repository:** `jotaele44/skywatcher-pr`
- **Audited commit:** `4be54a0de5022a8fd18ecff25d938287b90080b8`
- **Decision scope:** Diagnostic interactive airspace console and producer-side APIs
- **Production UI owner:** `thehub-pr`

## Context

Skywatcher currently has a React/Vite dashboard, a FastAPI diagnostic API, a stylized SVG Puerto Rico map, and a separate Python-generated Leaflet artifact. The generic entity API exposes the conceptual collections required by an airspace console, but several loaders intentionally return empty lists and the loaded observation package is synthetic. Historical timestamp parsing and same-aircraft screenshot fusion exist, but there is no time-indexed playback API.

The recording demonstrates 24 capability groups that depend on one synchronized viewport and clock. Implementing them as more isolated diagnostic pages would preserve the current fragmentation rather than reproduce the useful operational behavior.

## Decision

### 1. Add one diagnostic console route

Add `/console` as a new diagnostic route without removing the current pages. The console composes map, aircraft table, airport panel, playback, source visibility, layer controls, widgets, bookmarks, and preferences.

The existing pages remain focused review and inspection surfaces. The console is an operational visualization surface, not a replacement for evidence review.

### 2. Use MapLibre GL JS through a repository-owned adapter

Use `maplibre-gl` directly behind `MapRuntimeAdapter`; do not couple application state to MapLibre-specific objects.

Reasons:

- Supports interactive WebGL rendering.
- Supports vector, raster, GeoJSON, image, and custom sources.
- Supports dynamic GeoJSON updates for aircraft positions and tracks.
- Supports style-layer visibility, filters, symbols, lines, fills, heatmaps, and raster basemaps.
- Avoids binding the architecture to a React wrapper.

The existing static Leaflet export remains available for portable HTML reports.

### 3. Separate three data planes

1. **Operational aircraft state:** owned, licensed, public-official, or user-supplied position records.
2. **Screenshot evidence:** sparse OCR-derived observations and tracks with explicit uncertainty.
3. **Synthetic test data:** isolated fixtures that cannot be promoted to production output.

No adapter may scrape proprietary FlightRadar24 endpoints. FlightRadar24 screenshots remain evidence inputs only.

### 4. Introduce `/api/console/*`

Do not overload `/api/entities/*` with viewport, time-window, cursor, track-decimation, or playback semantics.

The console API uses typed response models, cursor pagination, UTC timestamps, row-level provenance, capability reporting, and explicit data-unavailable reasons.

### 5. Resolve source taxonomy by additive migration

Retain legacy `source_type` for reversible compatibility, mark it deprecated, and add:

- `source_family`
- `source_provider`
- `source_method`
- `data_rights`
- `operational_mode`
- `source_record_id`
- `source_taxonomy_version`

Frontend controls are generated from the canonical source-method registry rather than hardcoded aliases.

### 6. Use a pluggable user-state repository

Define `UserStateRepository`.

- Diagnostic implementation: namespaced `localStorage`.
- Future hub implementation: authenticated remote storage.

Bookmarks, columns, units, basemap choice, visible layers, widget layout, and recent selections are non-evidentiary state and do not mutate source artifacts.

### 7. Treat interpolation as display state, never evidence

Measured, stale-held, approximate, screenshot-derived, and display-interpolated positions are distinct states.

Default behavior:

- Operational tracks: measured points with gap segmentation.
- Screenshot evidence: no interpolation by default.
- Display interpolation: opt-in, ephemeral, never persisted, never exported as measured.
- Every interpolated state carries both parent point IDs and a visible disclosure.

### 8. Preserve the producer/hub boundary

Skywatcher owns:

- Schemas, ingestion, normalization, tracks, replay APIs, map-ready layers, and a diagnostic console.
- Provenance and export contracts.

The hub owns:

- Production multi-node UI.
- Shared authentication and multi-user persistence.
- Cross-federation overlays and alerts.

## Proposed frontend structure

```text
frontend/src/pages/AirspaceConsole.jsx
frontend/src/components/console/
  AirspaceMap.jsx
  MapRuntimeAdapter.js
  MapLayerRegistry.js
  BasemapRegistry.js
  AircraftViewportTable.jsx
  ColumnRegistry.js
  AirportPanel.jsx
  PlaybackController.jsx
  TimelineBar.jsx
  SourceVisibilityPanel.jsx
  LayerControlPanel.jsx
  WidgetDock.jsx
  BookmarkPanel.jsx
  PreferencesPanel.jsx
  GeolocationControl.jsx
  SparseEvidenceDisclosure.jsx
frontend/src/lib/console/
  ConsoleStateContext.jsx
  UserStateRepository.js
  LocalStorageUserStateRepository.js
  UnitProvider.jsx
  unitConversions.js
  playbackModel.js
```

## Proposed backend structure

```text
server/backend/console/
  router.py
  models.py
  capabilities.py
  pagination.py
  time.py
  provenance.py
  repositories/
    aircraft_state_repository.py
    flight_repository.py
    airport_repository.py
    layer_repository.py
  services/
    playback_service.py
    track_decimation.py
    screenshot_disclosure.py
    source_taxonomy.py
```

## Consequences

### Positive

- One synchronized operational surface.
- Clear producer/hub boundary.
- No silent empty-feature behavior.
- Reversible source-taxonomy migration.
- Offline diagnostic state remains local.
- Sparse evidence cannot masquerade as continuous tracking.

### Costs

- Adds a map runtime to the frontend.
- Requires a normalized local operational database.
- Requires new backend routers and response models.
- Airport operational parity remains adapter-dependent.
- Production UI work must later be repeated or shared in the hub.

## Alternatives considered

### Keep the SVG shell

Rejected. It cannot provide real geographic navigation, tile sources, viewport queries, or layer composition.

### Promote the static Leaflet report into the primary UI

Rejected as the primary architecture. It is useful for portable reports but is not integrated with React state, playback, typed APIs, or synchronized tables.

### Use the generic entity API for playback

Rejected. Offset-less, fixed-limit entity lists cannot represent viewport/time-window queries, stable cursor pagination, track decimation, or capability availability.

### Persist diagnostic state through the backend

Rejected for v0.1. It would turn a read-only diagnostic app into a multi-user state service and blur the hub boundary.

## Implementation gate

Phase 1 and Phase 2 implement the approved contracts. Later phases remain gated by separate review and authorization.
