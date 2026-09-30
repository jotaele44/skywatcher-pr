---
name: screenshot-to-mfl
description: "Stage newly supplied screenshot/PDF/ZIP evidence in Skywatcher, preserving provenance and deriving reviewable aircraft-field observations without fabricating canonical flight history."
version: 0.1.0
provenance_tier: SPEC_AUTHORED
status: INITIAL_IMPLEMENTATION_NOT_CERTIFIED
---

# Screenshot to Master Flight Log

## Activation

Activate for operator-supplied aviation screenshots or mixed screenshot packets intended to enrich Skywatcher's Master Flight Log. Automatically route to the existing RLSM engine; do not invent another OCR or flight-history authority.

## Required inputs

Authorized local source bytes, frozen source labels, SHA-256 receipt, processing settings, and a validated local execution environment. Optional inputs: existing Master Flight Log snapshots, independent native trajectory files, prior adjudications and known source flight IDs.

## Execution

1. Authenticate. Reject implicit local-network write access.
2. Inventory all outer sources and reachable PDF pages or ZIP members. Fail closed on unreadable members; preserve distinct member paths even when bytes match.
3. Freeze source bytes, container identity, derived-render identity, settings, and versions before extraction.
4. Reuse existing RLSM screenshot payloads by exact SHA-256, never by normalized filenames or perceptual proximity.
5. Run local OCR with zone and field provenance. Treat no usable OCR as BLOCKED rather than PASS.
6. Preserve all registration, callsign, altitude, speed, heading, operator-label and text observations as provisional.
7. Detect same-frame contradictions. Suppress any selected field affected by unresolved conflicting source strings.
8. Discover all plausible source-flight candidates against read-only corpus snapshots. Callsign similarity is discovery, not binding.
9. Emit complete item and stage receipts, including blocked and failed items, and expose them to the review UI.
10. Permit explicit reviewed annotations. Stop before canonical flight-history mutation without a separate certified promotion contract.

## Identity and interpretation restrictions

- SOURCE_MANIFESTATION != BYTE != SCREENSHOT != FLIGHT_ID != AIRFRAME != REGISTRATION != CALLSIGN.
- Displayed speed and altitude are point/screen observations, never necessarily flight maxima.
- Rendered trail is not timestamped raw telemetry. Missing native CSV/KML remains unknown.
- Proximity, same callsign, same registration, familiar operator label, and repeated appearance cannot prove a flight link.
- Every candidate match remains CANDIDATE_NOT_IDENTITY unless a separate authoritative gate validates the required binding.
- Preserve raw names, mojibake, spacing, detected conflicts, NULL values and every matching candidate; no arbitrary top-one selection.

## Required output

Job ID; frozen source and member manifest; per-stage terminal statuses; exact hashes; raw OCR IDs; field-level provisional observations; contradiction ledger; full corpus candidate set; review annotations; counted source/retained/blocked/failed totals; bounded certification state.

## Regression and certification

Positive: exact duplicate bytes at two filenames preserve two manifestations while reusing one OCR payload; valid OCR fields receive source receipts and the original corpus remains unchanged.

Negative: malformed ZIP, path traversal, empty ZIP/PDF, source hash drift, missing local OCR, conflicting registrations, unmatched callsigns, truncated candidate sets, or absent gold truth cannot produce a certified success.

Pre-release gate: Python and browser tests PASS, independent operator corpus audit PASS, 300 independently annotated screenshot gold sample PASS including >=98% location-label recall, identity/field accuracy gates defined and passed, zero unresolved residue inside the specific certified claim.

## Current status

INITIAL_IMPLEMENTATION_NOT_CERTIFIED. Upload, inventory, persistent jobs, local RLSM OCR, provisional candidates and review-only UI are code-delivered. Vision, perceptual dedup, cross-frame binding, canonical MFL writes, full SATIM/FPIM/CORRIM handoff and production certification remain OPEN or BLOCKED until evidence exists.
