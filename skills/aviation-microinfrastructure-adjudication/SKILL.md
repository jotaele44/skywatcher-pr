---
name: aviation-microinfrastructure-adjudication
description: >-
  Adjudicate aviation micro-infrastructure, airport endpoint candidates, and
  landing-zone associations without promoting proximity, names, addresses, or
  nearest-neighbour results into identity. Use for hangar, apron, helipad, FBO,
  terminal-event, and authoritative airport-geometry work.
default_mode: write_guarded
allowed_modes: [read_only, write_guarded]
owner_repo: jotaele44/skywatcher-pr
---

# aviation-microinfrastructure-adjudication

Use this skill when determining what an airport-adjacent object is, who operates
it, whether an aircraft endpoint is associated with it, or whether a geometry is
strong enough for point-in-polygon/topological adjudication.

## Non-negotiable separations

Keep `RAW`, `NORMALIZED`, and `CANONICAL` names separate. Keep source
manifestation, geometry, operator identity, physical class, and event association
as independent dimensions. A deterministic nearest result is still discovery.

Never prove identity from `NAME_ONLY`, `NORMALIZED_NAME_ONLY`, `COUNT_EQUALITY`,
`NEAREST_ONLY`, `PROXIMITY_ONLY`, `SAME_CATEGORY`, `ADDRESS_ONLY`, or source
absence. Preserve every candidate and tied top evidence state.

## Evidence order

Prefer stable ID, then authoritative binding, then certified machine geometry,
then geometry plus an independent alias/ID, then authoritative alias with
spatial/temporal support, then historical continuity plus corroboration. Treat
proximity as discovery only and unresolved ties as `UNRESOLVED`.

## Geometry states

Do not equate an authoritative airport diagram with certified machine geometry.
An FAA airport diagram may establish authoritative cartographic feature-class
presence and topology while individual building/apron/helipad polygons remain
`OPEN`.

For exact spatial adjudication, return only:
`FULLY_WITHIN|PARTIAL|TOUCH_ONLY|OUTSIDE|NULL_EMPTY|UNRESOLVED`.

Preserve CRS, geometry type, Z/M state, source URL/service/layer/query, retrieval
UTC, raw bytes where acquired, SHA256, and schema/count metadata. If geometry is
not available, fail closed to `UNRESOLVED` rather than deriving an exact polygon
from a label or POI centroid.

## Endpoint and route promotion

Track endpoints are not takeoffs or landings. Nearest-airport distance candidates
must carry `identity_state=CANDIDATE_NOT_IDENTITY` and
`association_state=DISCOVERY_ONLY`. They must not overwrite source/OCR route
fields. Route promotion requires explicit review state `promoted`, certified
facility identity, and an association state stronger than discovery-only.

## Regression gates

Positive gates:
- stable ID may certify identity;
- certified geometry plus an independent alias/ID may certify identity;
- explicitly promoted + certified endpoint association may update route fields.

Negative gates:
- helicopter presence != helipad;
- marked H != operator identity;
- address != building polygon identity;
- nearest airport != origin/destination;
- nearest hangar != facility identity;
- airport adjacency != aviation facility;
- authoritative cartographic diagram != certified machine geometry.

## Certification

Use `PASS|FAIL|OPEN|BLOCKED|PROVISIONAL|AUDIT_ONLY|NONCANONICAL|CANDIDATE_NOT_IDENTITY|UNRESOLVED|SUPERSEDED`.
A software test pass is not geometry certification. `CERTIFIED` requires frozen
inputs, explicit scope, complete classification within the bounded denominator,
arithmetic closure, validated IDs, passed tests, frozen hashes, and zero
unresolved residue inside the claim.

## Required outputs

Emit the frozen source/commit snapshot, source manifestations, candidate ledger,
identity/geometry/event states, contradictions, regression results, blockers,
and the next safe evidence vector. Never silently mutate a prior certified
artifact when new evidence arrives.
