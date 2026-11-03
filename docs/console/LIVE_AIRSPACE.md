# Live airspace map (`/live`)

`/live` is an adsb.lol-equivalent live map inside the diagnostic dashboard. It
reproduces every control, layer and data source of the adsb.lol web map (which
runs tar1090) shown in the reference recording of 2026-11-03, using public
upstream services only. The decision record is
[ADR-0003](../adr/0003-live-public-feed-map.md).

It is a diagnostic surface like the rest of this dashboard (ADR 0001): nothing on
this page is persisted or exported. To store adsb.lol positions, run the poller:
`python scripts/adsb_poll.py --provider adsblol`.

## Function map

Every function in the recording and where it lives here.

| Recording (adsb.lol) | `/live` equivalent | Code |
|---|---|---|
| Map pans/zooms from Puerto Rico to New York with live aircraft | MapLibre map, viewport remembered per browser, aircraft polled every 5 s (configurable) for the visible area | `pages/LiveAirspace.jsx`, `live/liveMapEngine.js` |
| Aircraft icons shaped by type, coloured by altitude, rotated by track | SDF silhouettes (airliner, heavy, small jet, prop, helicopter, glider, balloon, UAV, ground vehicle) tinted on the tar1090 altitude scale; red outline for squawk 7500/7600/7700 | `live/aircraftIcons.js`, `live/aircraftModel.js` |
| Map dimmed | Map dim on by default at 45 %; `B` or Settings toggles and adjusts it | `liveMapEngine.setDim` |
| **U** — only military aircraft | `military=true` → adsb.lol `/v2/mil` (global list, cut to the view) | `live_router.live_aircraft` |
| **H** — home / reset map | Returns to the home view (Puerto Rico; Settings can set it) and clears selection, follow and isolate | `LiveAirspace.resetMap` |
| **T** — all tracks | Trails for every aircraft in view | `LiveAirspace.renderMap` |
| Replay button (▶) | Replay bar; see below | `components/live/ReplayBar.jsx` |
| Layers button + layer menu (`»` closes it) | Same entries, groups and order as the adsb.lol menu | `components/live/LayerMenu.jsx`, `live/sourceCatalog.js` |
| `<` — sidebar | Aircraft list for the view (sortable: callsign, type, squawk, altitude, speed, distance, heading) and selected-aircraft details: registration, type, operator, altitudes, speed, vertical rate, position, source, route, trace size | `components/live/AircraftSidebar.jsx` |
| Fullscreen | Fullscreen API on the map; CSS fallback where the API is missing (iPhone) | `LiveAirspace.toggleFullscreen` |
| Settings cog | Units (nautical / imperial / metric), map dim, range-ring distances, refresh interval, local time zone, set home, reset | `components/live/SettingsPanel.jsx` |
| **L** — labels | Callsign labels | `aircraftModel.labelText` |
| **O** — label extensions | Adds altitude, speed and type to labels | `aircraftModel.labelText` |
| **K** — track labels | Altitude and UTC time along the selected aircraft's track | `LiveAirspace.renderMap` |
| **M** — multi-select | Clicks add to the selection (Ctrl/⌘-click works too) | `LiveAirspace.select` |
| **P** — persistence mode | Aircraft that leave the feed stay on the map, marked stale | `aircraftModel.mergeSnapshot` |
| **I** — isolate | Only selected aircraft are shown | `aircraftModel.visibleAircraft` |
| **R** — follow a random plane | Picks a random airborne aircraft in view, selects and follows it | `LiveAirspace.followRandom` |
| **F** — follow | Keeps the selected aircraft centred | `LiveAirspace.renderMap` |
| Selecting an aircraft | Loads its full-day trace and route; the trail is drawn coloured by altitude | `live_router.live_trace`, `live_router.live_routes` |
| `+` / `−`, scale bar in NM, attribution | Zoom buttons, MapLibre scale bar following the unit setting, full attribution (Esri, OSM, adsb.lol ODbL, …) | `liveMapEngine` |
| Keyboard letters in button titles | `U H T L O K M P I R F`, `Y` replay, `B` dim, `Esc` clear | `LiveAirspace` keydown handler |

### Replay bar

As on adsb.lol: **Play/Pause**, a UTC date picker, an hour slider, a minute
slider and a speed slider (cubic, 1×–1000×, default 30×). It shows the UTC date,
`UTC: hh:mm:ss / AST: hh:mm:ss` (the browser's zone, or the zone in Settings),
the local date, and `Loading …` while a chunk downloads.

adsb.lol publishes history as half-hour chunks and the half hour in progress is
not published yet, so opening replay (or asking for a time after the newest
chunk) starts one minute into the newest complete half hour — 16:01 UTC in the
recording, taken at 16:32 UTC. The backend downloads the chunk once, decodes it
(`adsb/heatmap.py`), and returns only the slices for the view, five minutes at a
time. Completed chunks are cached under `data/cache/adsblol/` (git-ignored).

Replay data has no heading, type or registration, so headings come from
successive positions and type/registration from what the live feed or a trace
already reported for that aircraft. `U` in replay therefore only shows aircraft
already known to be military.

## Data sources

### Aircraft data (through the backend)

The browser cannot call these directly: api.adsb.lol sends no CORS headers, and
replay chunks are ~15 MB. All aircraft data is © adsb.lol contributors under
ODbL 1.0, credited in the map attribution and the sidebar.

| Feed | Upstream | Backend endpoint |
|---|---|---|
| Live aircraft for the view | `https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}` (radius ≤ 250 NM) | `GET /api/console/live/aircraft?bbox=` |
| Military only (U) | `https://api.adsb.lol/v2/mil` | `GET /api/console/live/aircraft?bbox=&military=true` |
| Selected aircraft outside the view | `https://api.adsb.lol/v2/hex/{hex}` | `…/aircraft?hex=` |
| Traces | `https://adsb.lol/data/traces/{xx}/trace_full_{hex}.json` (today), `https://adsb.lol/globe_history/YYYY/MM/DD/traces/…` (past days) | `GET /api/console/live/trace/{hex}?date=` |
| Replay | `https://adsb.lol/globe_history/YYYY/MM/DD/heatmap/NN.bin.ttf` | `GET /api/console/live/replay?ts=&bbox=&window_s=` |
| Routes | `POST https://api.adsb.lol/api/0/routeset` | `POST /api/console/live/routes` |
| Feed configuration | — | `GET /api/console/live/status` |

When the view is wider than the 250 NM upstream radius, the status line says
"zoom in for full coverage". Upstream failures come back with HTTP 200 and
`status: "upstream_unavailable"` plus a fixed, user-safe reason, which the page
shows; the underlying error (URLs, network details) is only written to the
backend log. Malformed requests are HTTP 422.

The adsb.lol web map's own `re-api` endpoint is behind a bot-verification
challenge and is not used.

### Basemaps and overlays (fetched by the browser)

All of these send CORS headers and are loaded directly by MapLibre; the table
matches the adsb.lol layer menu.

| Group | Layer | Kind | Upstream |
|---|---|---|---|
| Worldwide | OpenStreetMap | base | `tile.openstreetmap.org` |
| | ESRI.com Satellite (default) | base | `services.arcgisonline.com` World_Imagery |
| | OpenStreetMap DE | base | `{a-d}.tile.openstreetmap.de` |
| | OpenFreeMap Bright / Liberty / Positron / Dark / Fiord | base (vector) | `tiles.openfreemap.org/styles/…` |
| | ESRI.com Sat. | base | `server.arcgisonline.com` World_Imagery |
| | ESRI.com Gray | base | `services.arcgisonline.com` World_Light_Gray_Base |
| | ESRI.com Streets | base | `services.arcgisonline.com` World_Street_Map |
| | GIBS Clouds (yesterday, UTC) | base | NASA GIBS MODIS Terra true colour |
| | ESRI.com Geography Labels | overlay | `services.arcgisonline.com` Reference/World_Boundaries_and_Places |
| | openAIP TMS | overlay | `api.tiles.openaip.net` via `GET /api/console/live/tiles/openaip/{z}/{x}/{y}.png` (needs `OPENAIP_API_KEY`) |
| | RainViewer Radar | overlay | `api.rainviewer.com/public/weather-maps.json`, refreshed every 2 min |
| US | VFR Sectional / VFR Terminal / IFR Enroute Low / IFR Enroute High | base | FAA charts on `tiles.arcgis.com` |
| | TFRs | overlay | `wiedehopf/tar1090-aux` `tfrs.geojson`, refreshed every 5 min |
| | Special Use Airspace | overlay | FAA ADDS open data (`opendata.arcgis.com`) |
| | NEXRAD | overlay | Iowa Environmental Mesonet `nexrad-n0q-900913`, refreshed every 2 min |
| | NOAA Infrared Sat | overlay | `nowcoast.noaa.gov` WMS `global_longwave_imagery_mosaic`, every 15 min |
| | NOAA Radar | overlay | `nowcoast.noaa.gov` WMS `base_reflectivity_mosaic`, every 5 min |
| | US A2A Refueling, US ARTCC Boundaries | overlay | tar1090 GeoJSON |
| Europe | DWD RADOLAN | overlay | `maps.dwd.de` WMS `dwd:RADOLAN-RY`, 5-minute buckets |
| | PL / NL / DE AWACS Orbits, DE Low Flying Areas, UK Radar Corridors, UK A2A Refueling, UK AWACS Orbits | overlay | tar1090 GeoJSON |
| Custom | Custom tiles | base | any `https://…/{z}/{x}/{y}` template entered in the menu |

The tar1090 GeoJSON layers are read at runtime from GitHub at the commit pinned
in `TAR1090_COMMIT` (`frontend/src/live/sourceCatalog.js`); nothing is copied
into this repository. TFRs use the live `tar1090-aux` feed because they change
constantly.

Two adsb.lol layers come from adsb.lol's private tile proxy, which is not meant
for other sites. They use the same upstreams directly instead: Esri's public
reference-label tiles for "ESRI.com Geography Labels", and openAIP's official
tile API (free key) for "openAIP TMS".

The top of the menu holds the aircraft and map-feature layers: **Aircraft pos.
webGL** (off draws simple dots, for weak devices), **Aircraft positions**,
**Aircraft trails**, **Your position** (browser geolocation, only while enabled)
and **Range rings** (100/150/200 by default, around your position or home).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAIP_API_KEY` | unset | Enables the openAIP overlay (backend only; never sent to the browser) |
| `ADSBLOL_API_BASE` | `https://api.adsb.lol` | adsb.lol API |
| `ADSBLOL_SITE_BASE` | `https://adsb.lol` | traces and replay chunks |
| `ADSBLOL_CACHE_TTL_S` | `2` | identical requests within this window are answered from memory |
| `ADSBLOL_CACHE_DIR` | `data/cache/adsblol` | completed replay chunks |
| `ADSBLOL_MAX_RADIUS_NM` | `250` | upstream query radius cap |

Browser preferences (base layer, overlays, labels, units, dim, rings, home, time
zone) are stored in `localStorage` under `skywatcher.live.settings.v1`; the
viewport under `skywatcher.live.viewport.v1`.

## Tests

- Backend: `tests/test_adsb_heatmap.py`, `tests/test_adsb_lol_provider.py`,
  `tests/test_console_live_api.py` (fake HTTP; no network).
- Frontend unit: `frontend/src/live/*.test.js`,
  `frontend/src/components/live/LiveControls.test.jsx` — including a check that
  the layer menu lists exactly the recording's entries in order.
- E2E: the `live airspace map …` test in `frontend/tests/gui-parity.spec.mjs`
  (stubbed feeds) plus the manifest-driven route test.

## Known limits

- openAIP needs a free API key; without it the overlay is disabled in the menu.
- The routeset API often answers with no body; the sidebar then shows the route
  as unknown.
- Replay covers complete half hours only, as on adsb.lol.
- Some IFR High chart tiles do not exist upstream (open ocean) and return 404.
