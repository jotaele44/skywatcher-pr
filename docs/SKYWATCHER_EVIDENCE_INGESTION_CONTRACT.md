# Skywatcher Federated Evidence Ingestion Contract

Status: **GOVERNING CONTRACT / FAIL-CLOSED**

## Purpose

A newly supplied evidence batch may be a native screenshot/image, a PDF whose pages contain screenshots, a ZIP whose members contain screenshots or related structured data, or a mixed batch. Skywatcher must automatically inventory the complete accessible denominator, preserve provenance/source manifestation identity, determine applicable analytical capabilities, route the batch to the correct skills, and keep observation, interpretation, association, identity, mission, and anomaly states separate.

The user must not need to manually name a skill or pipeline.

## Required execution order

1. Detect outer container type.
2. Freeze source bytes where accessible: filename/path, size, SHA-256, upload/retrieval context.
3. Enumerate the complete accessible page/member/file denominator.
4. Preserve page/member/source manifestation separately from logical/event identity.
5. Detect duplicates without collapsing distinct source paths.
6. Classify evidence kinds and construct the capability set.
7. Route through the skill registry.
8. Execute applicable visual/identity/spatial/trajectory/temporal/altitude/site/infrastructure/behavior vectors.
9. Run contradiction and false-promotion gates.
10. Create/update golden regression fixtures for reusable failure modes.
11. Generalize only after the triggering fixture passes.
12. Freeze successor build/manifest/hash only after regression closure.

## Evidence-state vocabulary

Use `FACT`, `COMPUTED`, `BINDING`, `INFERENCE`, `ASSUMPTION`, `HYPOTHESIS`, `UNKNOWN`.

Certification states are `PASS`, `FAIL`, `OPEN`, `BLOCKED`, `PROVISIONAL`, `AUDIT_ONLY`, `NONCANONICAL`, `CANDIDATE_NOT_IDENTITY`, `UNRESOLVED`, `SUPERSEDED`.

Script success or deterministic output is never certification.

## Source/container identity

Maintain separately:

- BYTE identity
- LOGICAL identity
- SCHEMA identity
- GEOMETRIC identity
- SOURCE_MANIFESTATION identity
- EVENT identity
- SCREENSHOT identity
- PDF PAGE identity
- ARCHIVE MEMBER identity

Different hashes prove only byte difference. Different ZIP hashes do not prove different member payloads. For archive comparison, preserve member path, uncompressed size, SHA-256, and the payload multiset `(SIZE, SHA256)`.

## Container rules

### Native images

Hash and preserve the original byte payload. Treat metadata, visible UI text, route rendering, labels, aircraft marker, and map content as distinct observations.

### PDFs

The PDF is the source container. Pages are page manifestations. A page rendering or embedded image is not byte-identical to the PDF container. OCR text must not replace visual interpretation where map geometry, trails, icons, labels, or UI state matters.

### ZIP/archive

Inventory every member before semantic analysis. Preserve exact member path, size, hash, media type, duplicate payload relationships, unreadable members, and nested-container status. Do not collapse duplicate payloads at different paths.

### Mixed batches

Preserve every source separately and derive a batch-level manifest without synthesizing source identities.

## Capability routing

Container type is not analysis logic. All visual manifestations route to the same applicable visual capability family while preserving different source manifestations.

The registry must be capable of routing to, when applicable:

- RLSM
- FR24 screenshot inventory
- aircraft identity
- aircraft marker detection
- route extraction
- FPIM
- CORRIM
- SATIM
- TIMELINE
- PATTERN
- altitude validity
- stop/hover/landing/takeoff adjudication
- source identity binding

Capability matching takes precedence over exact historical module names.

## Mandatory false-promotion gates

1. `BAROMETRIC_ZERO_TRAP`: `0 ft` must never imply `ON_GROUND` by itself.
2. `STOP_NOT_LANDING`: `0 mph`, route termination, or icon stationarity must never certify landing by itself.
3. `POI_PROXIMITY_FALSE_TARGET`: nearest/prominent POI or map label is discovery only.
4. `RENDERED_TRAIL_NOT_RAW_TRAJECTORY`: rendered route lines are separate from raw telemetry.
5. `OWNER_OPERATOR_MISSION_SEPARATION`: registered owner, operator, tracker label, maintenance responsibility, and mission authority are distinct.
6. `CORRIDOR_ALIGNMENT_NOT_MISSION_IDENTITY`: infrastructure alignment may support association but never exact mission identity by itself.
7. RAW, NORMALIZED, and CANONICAL values remain separate.
8. Nulls, ties, duplicates, M:N joins, geometry uncertainty, ordering, and library semantics fail closed when they can alter the conclusion.

## Identity rules

Never prove identity using name-only, normalized-name-only, count equality, nearest-only, proximity-only, same-category, or source absence. Permit `1:1`, `1:N`, `N:1`, `N:N`, `0:1`, and `UNRESOLVED`.

Evidence priority is stable ID -> authoritative binding -> certified geometry -> point-in-polygon plus independent alias/ID -> point-in-polygon -> authoritative alias with spatial/temporal support -> historical continuity plus corroboration -> proximity -> unresolved.

## Spatial and temporal rules

Preserve CRS, geometry type, uncertainty, and geometry provenance. Final spatial states are `FULLY_WITHIN`, `PARTIAL`, `TOUCH_ONLY`, `OUTSIDE`, `NULL_EMPTY`, `UNRESOLVED`.

Preserve separate clocks for screenshot capture time, device local time, application display time, track point time, source server time, file metadata time, ingest time, and map imagery time. Do not assume equality.

## Landing/takeoff state ladder

Use:

`MOVING -> DECELERATING -> STATIONARY_POSITION -> HOVER_OR_GROUND_UNRESOLVED -> LANDING_CANDIDATE -> LANDING_CERTIFIED`

and separately:

`GROUND_POSITION -> DEPARTURE_CANDIDATE -> TAKEOFF_CERTIFIED`

Independent evidence is required for certification.

## Contradiction ledger

Never silently reconcile conflicting observations. Preserve and classify contradictions as applicable: BYTE, SCHEMA, GEOMETRY, NAME, COUNT, CLASS, IDENTITY, TIME, SCOPE, ALTITUDE, SPEED, MODEL, OWNER_OPERATOR, MISSION, ROUTE. Displaced interpretations remain `SUPERSEDED`.

## Invariants

Close source/container/member/page/retained/excluded/unreadable/duplicate counts. Validate required fields, stable IDs, coordinates, geometry/null state, row conservation, join cardinality, and absence of unintended loss/duplication/multiplication. Unexplained arithmetic mismatch fails closed.

## Golden fixtures

A reusable fixture records: fixture ID, source manifest, expected facts, expected non-facts, expected inferences, prohibited promotions, expected certification states, unresolved fields, contradictions, and positive/negative regressions.

Prohibited promotions include:

- `0_FT -> ON_GROUND`
- `0_MPH -> LANDED`
- `MAP_LABEL -> TARGET`
- `NEAREST_POI -> TARGET`
- `OWNER -> OPERATOR`
- `OPERATOR -> MISSION`
- `RENDERED_TRAIL -> RAW_TRAJECTORY`
- `CORRIDOR_ALIGNMENT -> EXACT_MISSION`

## Certification

Certification is bounded. It requires defined scope, frozen inputs, explicit inclusion/exclusion, complete scoped classification, duplicate/chronology adjudication, arithmetic closure, validated identities where claimed, bounded spatial uncertainty, passed relevant tests, frozen hashes where byte identity matters, and zero unresolved residue inside the certified claim.

A blocked vector must not erase already passed independent artifacts. After downstream failure, reuse passed artifacts and do not redownload mutable sources unless deliberately creating a new snapshot.

## Router implementation

`src/skywatcher/evidence_router.py` is the stdlib-first ingestion/router layer. It inventories native image, PDF, ZIP, structured, and mixed manifestations; produces a skill route plan; preserves container/source differences; and emits fail-closed gates. It does not replace downstream analytical modules.

CLI:

```bash
python scripts/route_evidence_batch.py screenshot.jpg
python scripts/route_evidence_batch.py evidence.pdf
python scripts/route_evidence_batch.py batch.zip
python scripts/route_evidence_batch.py screenshot.jpg track.json evidence.pdf --output reports/evidence_route.json
```

The router's `ANALYTICAL_CERTIFICATION` gate intentionally remains `OPEN` until downstream execution and regression closure occur.
