# Interactive Airspace Console Phase 3

## Boundary

Phase 3 adds a browser-only MapLibre GL JS runtime and a `/console` shell. It does not add network collectors, FlightRadar24 endpoint access, proprietary visual assets, playback, live aircraft rendering, or production federation mutations.

The backend remains the producer boundary. The frontend reads `/api/console/capabilities` and installs only layers whose capability status is `available`, `available_synthetic_only`, or `degraded`.

## Runtime modules

- `basemapRegistry.js` — immutable offline-first basemap registry.
- `layerRegistry.js` — capability-gated local and operational layer declarations.
- `viewportState.js` — bounded, persistent camera state.
- `selectionState.js` — explicit coordinate/feature selection model.
- `mapRuntimeAdapter.js` — MapLibre construction, controls, event binding, layer installation, and deterministic cleanup.
- `MapRuntime.jsx` — React lifecycle wrapper with `ResizeObserver` cleanup.
- `Console.jsx` — `/console` route and base console shell.

## Offline baseline

`local-blank-diagnostic` is a complete MapLibre Style Specification object with:

- no tile URLs;
- no glyph URLs;
- no sprite URLs;
- no provider keys;
- no runtime network requirement;
- a local diagnostic background layer.

A local non-authoritative Puerto Rico extent rectangle and selection layer are installed after the style loads. They are diagnostic geometry only.

## Attribution

MapLibre attribution is installed explicitly through `AttributionControl` with `compact: false`. The console also repeats the active basemap attribution in a persistent status strip. No code path intentionally hides attribution.

## Capability promotion

Phase 3 promotes only:

- `map_navigation`;
- `geolocation`;
- `basemap_controls`.

Playback, viewport aircraft, operational airport state, aircraft labels, ATC overlays, day/night, and map-brightness controls remain unavailable or degraded according to actual implementation and repository state.

## Cleanup

`createMapRuntime().destroy()`:

1. removes all registered event handlers;
2. removes every runtime-installed control;
3. calls `map.remove()` once;
4. is idempotent.

The React wrapper disconnects its `ResizeObserver` before invoking runtime destruction.

## Preservation

Phase 3 preserves the existing pages, `PuertoRicoMapShell`, static Leaflet reports, desktop wrapper, generic entity API, Phase 1 schemas/migrations, and Phase 2 repository/query services.
