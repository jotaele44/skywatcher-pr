# ADR-0003: Live public-feed map at `/live`

- **Status:** Accepted
- **Amends:** [ADR-0002](0002-interactive-airspace-console.md) (single diagnostic console route)
- **Production UI owner:** `thehub-pr` (unchanged)

## Context

The operator asked for an equivalent of every function and data source shown in
a recording of the adsb.lol web map (tar1090): live aircraft over a satellite
basemap, the U/H/T/replay and L/O/K/M/P/I/R/F buttons, the layer menu with its
basemaps and weather/airspace overlays, the aircraft sidebar, and half-hour
replay.

`/console` (ADR-0002) is deliberately offline-first: its default style has no
network sources and its capability registry reports only repository-backed
data. The adsb.lol feature set is the opposite: every layer and the aircraft
feed are third-party network services.

## Decision

1. Add a separate full-bleed route, `/live`, for public network feeds. `/console`
   keeps its offline baseline and its 24-entry capability registry unchanged.
2. Aircraft data comes from adsb.lol through backend endpoints under
   `/api/console/live/*`, implemented by `adsb/providers/adsblol.py` and
   `adsb/heatmap.py`. The backend is needed because api.adsb.lol sends no CORS
   headers, replay chunks must be cut to the viewport, and the openAIP key must
   stay server-side.
3. Only documented or plainly public endpoints are used. The adsb.lol `re-api`
   (bot-verification protected) and adsb.lol's private tile proxy are not used;
   their layers come from the same upstreams directly.
4. Basemaps and overlays are fetched by the browser from their public, CORS-enabled
   upstreams. Third-party airspace GeoJSON is read at a pinned commit, not copied.
5. Upstream failures are reported in-band (`status`, `reason`, HTTP 200) and
   rendered as offline/stale states.
6. Nothing on `/live` is persisted. `scripts/adsb_poll.py --provider adsblol` is
   the persistence path, through the existing `adsb_state_vectors` sink.

## Consequences

- `/live` requires network access; `/console` still works fully offline.
- adsb.lol data is ODbL 1.0 and is attributed on the map and in the sidebar.
- The openAIP overlay needs `OPENAIP_API_KEY` on the backend.
- The layer catalog lives in one place (`frontend/src/live/sourceCatalog.js`) and
  a unit test pins it to the recording's menu.

Details: [docs/console/LIVE_AIRSPACE.md](../console/LIVE_AIRSPACE.md).
