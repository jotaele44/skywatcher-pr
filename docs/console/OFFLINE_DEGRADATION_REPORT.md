# Phase 3 Offline Degradation Report

## Offline blank mode

| Surface | Offline behavior |
|---|---|
| Map canvas | Available when WebGL is available |
| Pan, zoom, bearing, pitch | Available |
| Viewport state | In-memory only |
| Selection state | In-memory only |
| Blank basemap | Available with zero provider requests |
| Attribution | Always visible |
| Geolocation | Device/browser dependent; explicit activation only |
| External basemap | Not configured and unavailable |
| Aircraft states | Repository dependent and capability gated |
| Track playback | Not implemented in Phase 3 |

## WebGL unavailable

The console displays a controlled `RuntimeUnavailable` panel. It does not retry continuously, construct a map, or crash the surrounding diagnostic application. Existing pages and `PuertoRicoMapShell` remain available.

## Backend unavailable

Capability bootstrap fails closed and displays an explicit local capability-service error. The map does not initialize without the capability contract.

## Feature rollback

Setting `VITE_SKYWATCHER_CONSOLE_ENABLED=false` disables the route runtime without reverting Phase 1 or Phase 2 database, API, schema, or repository work.
