# Phase 3 WebGL Resource Ledger

## Owned resources

| Resource | Acquisition | Release |
|---|---|---|
| MapLibre map | Adapter `create()` | `map.remove()` |
| Attribution control | After map construction | `map.removeControl()` |
| Navigation control | After map construction | `map.removeControl()` |
| `moveend` listener | Adapter initialization | `map.off()` |
| `load` listener | Adapter initialization | `map.off()` |
| `error` listener | Adapter initialization | `map.off()` |
| `ResizeObserver` | Adapter initialization | `disconnect()` |
| User-location layers | First explicit location result | `removeLayer()` |
| User-location source | First explicit location result | `removeSource()` |

`releaseAll()` executes in reverse acquisition order. `destroy()` is idempotent and asserts a zero active-resource balance.

## Validation

- Map create/remove balance: unit gate and browser gate.
- Observer create/disconnect balance: unit gate and browser gate.
- Twenty-five lifecycle cycles: unit gate and Chromium route-cycle gate.
- Remaining MapLibre canvases after final unmount: browser gate.
- Partially initialized adapters: cleanup gate.
