# Phase 3 Offline Degradation Report

## Baseline

The `/console` route must remain diagnostically usable when the browser has no network access after the application bundle has loaded.

## Offline behavior

| Surface | Offline result | Classification |
|---|---|---|
| MapLibre application bundle | Loaded from the locally built frontend bundle | Available |
| `local-blank-diagnostic` style | Renders without tiles, sprites, glyphs, or remote JSON | Available |
| Puerto Rico diagnostic extent | Inline GeoJSON | Available |
| Selection point | Local state and inline GeoJSON | Available |
| Navigation control | Local MapLibre control | Available |
| Geolocation | Browser/OS dependent; may require permission and device services | Degraded externally |
| Backend capability fetch | Uses local `/api/console/capabilities`; unavailable when the local backend is down | Degraded |
| Aircraft states | Remains capability-gated and empty without a repository artifact | Unavailable by artifact |
| Tracks/routes | Remains capability-gated and empty without a repository artifact | Unavailable by artifact |
| Airport operations | Remains capability-gated and empty without an official adapter/artifact | Unavailable by adapter/artifact |
| SVG fallback | Uses existing committed application code/data | Available |

## Failure modes

### WebGL unavailable

The React runtime reports the MapLibre construction error and the page renders `PuertoRicoMapShell` instead. No retry loop or orphaned WebGL context is retained.

### Capability endpoint unavailable

The page retains the capability error, does not force-enable operational layers, and presents the SVG diagnostic fallback.

### Geolocation denied or unavailable

The map remains navigable. The geolocation control is omitted when the browser lacks the API. Permission denial does not change map or data state.

### No operational artifacts

Operational layers are not populated with synthetic substitutes. Their checkboxes remain disabled according to capability status.

## Network and credential audit

The blank style is serialized and checked for `http://`, `https://`, `mapbox://`, `access_token`, `api_key`, and `apikey=` tokens. No provider keys are present in the Phase 3 source.

## Attribution

The runtime installs non-compact MapLibre attribution and the shell repeats the active attribution text. Offline operation does not suppress attribution.
