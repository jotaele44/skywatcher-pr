# Skywatcher Interactive Airspace Console — Phase 3 High Assurance

## Scope

Phase 3 adds a producer-side, non-production interactive diagnostic console at `/console`. It is a separate lazy-loaded frontend surface and does not replace the existing dashboard pages, the `PuertoRicoMapShell` SVG diagnostic component, static Leaflet exports, the desktop wrapper, or the PRII hub boundary.

## Runtime architecture

- MapLibre GL JS is pinned exactly to `5.24.0`.
- `MapRuntimeAdapter` is the sole module that constructs or owns a MapLibre map.
- The default basemap is an in-memory Style Specification with no tiles, URL, sprites, glyphs, credentials, or provider dependency.
- `RuntimeResourceLedger` owns maps, controls, listeners, observers, sources, and layers and provides idempotent teardown.
- Browser capability and backend capability must both pass before the map is enabled.
- Browser geolocation is activated only by an explicit button action and is neither persisted nor sent to the backend.
- Permanent attribution is rendered in the shell and through the MapLibre attribution control.

## Route and preservation boundary

- New route: `/console`.
- Existing routes remain registered and unchanged.
- The shared layout enters full-bleed mode only under `/console`.
- `SkywatcherDataProvider` skips legacy bulk entity hydration while the console route is active.
- Data layers, playback, aircraft symbols, external basemaps, brightness controls, bookmarks, and preference persistence remain outside Phase 3.

## Security and offline posture

- Blank mode performs no external map requests.
- Runtime style validation rejects remote URLs and credential-like keys recursively, including values in arrays such as `source.tiles[]`.
- The desktop same-origin server emits a restrictive Content Security Policy, disables object embedding, and limits geolocation to the local origin.
- No FlightRadar24 visual asset, provider key, sample token, or proprietary map URL is included.

## Assurance surface

- Vitest unit, component, defensive-branch, policy, and 25-cycle lifecycle tests.
- Playwright acceptance across Chromium, Firefox, and WebKit.
- Axe WCAG A/AA gate with zero serious or critical findings.
- Offline request accounting.
- WebGL unavailable fallback.
- Route regression checks.
- Visual geometry baseline and screenshot artifact.
- Browser memory/resource stability gate.
- Native pywebview WebGL probe under GTK/WebKit.
- npm production audit, CycloneDX SBOM, direct dependency license ledger, and CSP review.
