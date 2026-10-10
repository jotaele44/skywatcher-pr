# PITIRRE AIR

AIR is the first physically instantiated PITIRRE domain package.

## Subdomains

- `AIR.AVIATION` — aircraft/flight observations and source-declared aviation state.
- `AIR.AIRSPACE` — airspace observations and constraints.
- `AIR.AEROSTAT` — aerostat observations/state.
- `AIR.ATMOSPHERIC_SENSOR` — atmospheric sensor observations/state.

## Ownership boundaries

AIR is a physical-domain namespace, not an analytical owner.

- Core owns shared contracts and normalization.
- FPIM owns neutral flight-path/trajectory analysis.
- SATIM owns imagery interpretation.
- CORRIM owns cross-domain association/reconciliation.
- Mission or intent inference remains prohibited.
- Source-declared labels may be preserved as sourced metadata only.

## Current migrated surface

`events.py` is an AIR facade over the Core-owned AIR event normalizer and v2
contract validator. It deliberately contains no duplicate normalization logic.


## ADS-B migration

`aviation/adsb/` is the canonical implementation for automated ADS-B state
vectors, provider registry/configuration, OpenSky adaptation and persistence
sink behavior. The historical root `adsb/` package remains a compatibility
facade/alias surface.

ADS-B state vectors remain observations/source manifestations. They do not
establish aircraft identity by callsign alone and do not authorize mission or
intent inference.
