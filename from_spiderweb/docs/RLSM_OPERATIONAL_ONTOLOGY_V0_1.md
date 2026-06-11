# RLSM Operational Ontology v0.1

This document defines the first controlled vocabulary and registry layer for the Puerto Rico Airspace Intelligence System / RLSM workflow.

## Objective

Prevent FR24 OCR and screenshot-derived data from fragmenting operationally identical entities into separate strings. The ontology separates raw screenshot evidence from contextual registries so that locations, aircraft identities, operators, hangars, LZs, POIs, corridors, mission terms, and blackout terms are normalized before baseline OCR ingestion.

## Visibility classes

| Class | Meaning | Example |
|---|---|---|
| V0 | Directly visible in a screenshot or raw OCR field | tail number, N/A label, altitude, speed |
| V1 | Inferred from visible map geometry or track behavior | coastal loop, descent, hover, corridor-follow |
| V2 | Context-only project knowledge, manual registry, or prior analyst annotation | known LZ, hangar candidate, local alias, POI chain |
| V3 | External registry or authoritative lookup | FAA owner, ICAO hex, formal airport code |
| V4 | Hypothesis-only analytical label | ISR-like, utility-adjacent, government-adjacent |

## Required separation

The normalizer must keep these fields separate:

- airport_id
- ramp_id
- hangar_id
- lz_id
- poi_id
- corridor_id
- operator_id
- aircraft_id
- raw OCR text
- raw analyst note
- normalized canonical value
- visibility class
- evidence tier
- confidence score

Do not collapse airport, ramp, hangar, and LZ into a single origin/destination field.

## OCR baseline gate

The baseline OCR run is blocked unless all of the following pass:

1. Registry files load successfully.
2. Visibility classes are valid members of V0/V1/V2/V3/V4.
3. Evidence tiers are valid members of T1/T2/T3/T4.
4. Required operational registries exist.
5. Alias collisions are detected and routed to review instead of silently overwritten.
6. Common airport aliases resolve to one canonical ID.
7. `N/A`, blank, unknown, and suppressed identifiers resolve to unresolved identity classes, not to one aircraft.
8. Mission aliases resolve to closed mission enums.
9. Raw text is preserved beside normalized fields.
10. Unknowns remain explicit unresolved records, not null-filled guesses.

Run the gate from the repository root as a module so package imports resolve consistently:

```bash
python -m pipeline.rlsm_ontology_gate
pytest tests/test_rlsm_operational_ontology.py
```

## Evidence language

Use these labels:

- T1: technical or primary-source record
- T2: operational data, screenshot, ADS-B, flight log, or geospatial trace
- T3: eyewitness, human annotation, or local knowledge
- T4: secondary source or weak contextual reference

## Safety and confidence discipline

The ontology can support anomaly detection, ILAP triage, and BoGR ranking, but the output must remain evidence-bounded. A POI, LZ, or hangar candidate must retain its confidence score and evidence tier. Hypothesis labels are never promoted to fact without registry or repeated operational support.
