# External Aerodrome Layer (EAL)

## Purpose

The External Aerodrome Layer (EAL) is the upstream place-first index for non-Puerto-Rico aviation sites observed in FlightRadar24 screenshot data. It is designed to run before the Airframe Entity Layer so aircraft, operator, owner, and contract-graph work can be anchored to recurring external landing-site nodes.

EAL answers one question first:

> Which airports, airfields, airstrips, heliports, seaplane bases, ramps, MRO/FBO facilities, and landing-zone candidates outside Puerto Rico have appeared in the screenshot corpus?

## Scope

Included:

- Major airports outside Puerto Rico
- Regional airports outside Puerto Rico
- Private airstrips outside Puerto Rico
- Heliports / helipads outside Puerto Rico
- Seaplane bases outside Puerto Rico
- FR24 origin/destination labels outside Puerto Rico
- Map-visible runway or pad candidates outside Puerto Rico
- Facility nodes inside airport boundaries when operationally distinct, such as MRO, FBO, cargo, government, or contractor ramps

Excluded from EAL promotion:

- Puerto Rico airports and landing sites, which remain in the PR-side airspace layer and are used later for crosswalk scoring
- Pure aircraft observations with no place evidence
- Unsourced airport guesses not visible in screenshots or OCR text

## Puerto Rico Exclusion List

These are not promoted into the external ledger during EAL extraction. They may be referenced as crosswalk endpoints later.

| ICAO | IATA | Name |
|---|---|---|
| TJSJ | SJU | Luis Muñoz Marín International Airport |
| TJIG | SIG | Fernando Luis Ribas Dominicci / Isla Grande |
| TJBQ | BQN | Rafael Hernández Airport |
| TJPS | PSE | Mercedita Airport |
| TJRV | RVR | José Aponte de la Torre Airport |
| TJVQ | VQS | Antonio Rivera Rodríguez Airport |
| TJCP | CPX | Benjamín Rivera Noriega Airport |
| TJMZ | MAZ | Eugenio María de Hostos Airport |

## Core Outputs

| Output | Purpose |
|---|---|
| `external_aerodromes_master.csv` | Canonical deduplicated external landing-site ledger |
| `external_aerodromes_master.geojson` | GIS-ready point layer |
| `external_facility_nodes.csv` | MRO/FBO/ramp/facility sublayer |
| `external_landing_zone_review_queue.csv` | Unresolved airport, airstrip, pad, or runway candidates |
| `airport_code_aliases.csv` | ICAO/IATA/name alias table |
| `screenshot_airport_mentions.csv` | Provenance table linking screenshot/OCR evidence to candidate sites |

## Canonical Fields

| Field | Description |
|---|---|
| `site_id` | Stable identifier, e.g. `EAL-USA-FL-KOPF-0001` |
| `site_name` | Airport, strip, pad, heliport, or facility name |
| `icao` | ICAO code if available |
| `iata` | IATA code if available |
| `faa_lid` | FAA location identifier if applicable |
| `country` | Country or territory |
| `region_state` | State, territory, island, or province |
| `municipality_or_city` | Local jurisdiction |
| `lat` | Latitude, EPSG:4326 |
| `lon` | Longitude, EPSG:4326 |
| `site_class` | `airport`, `airstrip`, `heliport`, `seaplane_base`, `landing_zone`, `facility_node`, or `unknown` |
| `source_type` | `fr24_panel`, `map_label`, `ocr_text`, `visual_runway`, `manual_seed`, or `cross_platform` |
| `first_seen_utc` | First known screenshot observation |
| `last_seen_utc` | Last known screenshot observation |
| `seen_count` | Number of screenshot mentions or observations |
| `associated_aircraft` | Known callsigns, tails, ICAO hexes, or aircraft types |
| `associated_facility` | Facility node such as Ascendas, FBO, MRO, cargo ramp, or military ramp |
| `metadata_status` | `complete`, `partial`, `na`, `suppressed`, or `unknown` |
| `confidence` | Integer 0-100 |
| `review_status` | `quarantine`, `reviewed`, `promoted`, or `rejected` |
| `notes` | Analyst notes |
| `source_ref` | Screenshot path, OCR row, report row, or manual observation reference |

## Extraction Method

### Pass A: Deterministic OCR/Text Sweep

Search OCR outputs, extracted FR24 panel text, filenames, and analyst notes for:

```text
ICAO/IATA regex:
\bK[A-Z]{3}\b
\bT[A-Z]{3}\b
\bM[A-Z]{3}\b
\b[A-Z]{3}\b

Airport terms:
airport, airfield, airstrip, heliport, helipad, seaplane, executive, municipal, regional, international, aeropuerto, aeródromo, pista
```

### Pass B: Visual Map Sweep

For screenshots where OCR is weak or absent, flag:

| Visual feature | Candidate class |
|---|---|
| Long straight high-contrast strip | runway / airstrip |
| Parallel taxiway or apron geometry | airport / airfield |
| Circular pad or H marking | heliport / helipad |
| Dock or water-lane aviation label | seaplane base |
| Aircraft icon clusters around visible landing geometry | airport candidate |

### Pass C: Deduplication

Deduplicate in this order:

1. Exact ICAO match
2. Exact IATA + country/region match
3. FAA LID match
4. Name-normalized match within coordinate tolerance
5. Coordinate proximity with compatible class
6. Facility-node containment inside known airport boundary

Default rule:

```text
Same aerodrome if coordinates are within 500 m and names/codes do not conflict.
Separate facility node if it is inside an airport boundary but has a distinct operational role, such as MRO, FBO, cargo, government, or military ramp.
```

## Confidence Tiers

| Tier | Criteria |
|---|---|
| EAL-100 | ICAO/IATA confirmed + coordinate confirmed + repeated observation |
| EAL-90 | ICAO/IATA confirmed + single observation |
| EAL-75 | Name + coordinate confirmed |
| EAL-60 | Map label only + likely aviation geometry |
| EAL-40 | Visual runway/helipad candidate only |
| EAL-Q | Quarantine; requires manual review |

## Initial Seed Observations

These are seed observations from the current Ascendas / offshore Puerto Rico screenshot discussion. Only confirmed screenshot-observed items should be promoted.

| Site | Code | Region | Role | Status |
|---|---|---|---|---|
| Opa-locka Executive Airport | KOPF / OPF | Florida | MRO / charter / business aviation | promote |
| Ascendas Aerospace Group facility/ramp | within KOPF | Florida | MRO / staging / maintenance | facility-node quarantine until coordinate-verified |
| Henry E. Rohlsen Airport | TISX / STX | St. Croix, USVI | military/cargo/civilian corridor | promote |

## Crosswalk Strategy

EAL feeds later layers in this order:

```text
EAL -> Facility Node Layer -> Airframe Entity Layer -> PR Flight Crosswalk -> Contract-Sweeper Fusion -> Spiderweb Graph
```

Strong signal examples:

- Same non-PR airport repeatedly appears in screenshot routes involving Puerto Rico
- Same facility node recurs with suppressed aircraft metadata
- Same external aerodrome links to repeated tail/hex/callsign observations
- Same owner/operator later resolves into a Puerto Rico contract, infrastructure, or logistics entity

## Evidence Policy

EAL is a provenance-first layer. A site is not considered analytically meaningful because it appears once. It becomes meaningful when recurrence, entity overlap, or contract/infrastructure crosswalks converge.

Use these terms:

- `observed`: directly present in screenshot/OCR data
- `candidate`: inferred from visible map or partial OCR
- `promoted`: code/name/coordinate confirmed and deduplicated
- `quarantine`: retained but not used for scoring until reviewed

## Current Blind Spots

- FR24 zoom level can hide airport labels.
- FR24 destination fields can be incomplete, suppressed, or absent.
- OCR may confuse three-letter IATA codes with unrelated uppercase text.
- Facility nodes inside airports require coordinate verification before promotion.
- Screenshot-only coverage cannot prove all airports used by an aircraft; it can only prove all sites observed in the screenshot corpus.
