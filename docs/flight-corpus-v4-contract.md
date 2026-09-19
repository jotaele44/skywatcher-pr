# Skywatcher Flight Corpus V4 Integration Contract

Status: PROVISIONAL analytical baseline. This contract does not promote mission semantics.

## Frozen denominators
- 696 non-empty logical raw-flight records.
- 11 are single-point observations and are not trajectory-eligible.
- 685 trajectory-eligible logical tracks (>=2 spatial observations).
- Certified unordered trajectory-pair denominator: 685 * 684 / 2 = 234,270.
- 45 V3 consensus recurrent-geometry candidate families.
- 4 chaining-risk families require complete-link subdivision.
- 326 tracks belong to positive consensus geometry families.

## Required entity separation
AIRFRAME | REGISTRATION | CALLSIGN | FLIGHT_ID | SOURCE_FOLDER | OWNER | OPERATOR | MISSION

No field above is an alias for another without an independent temporal binding.

## Required states
FACT | COMPUTED | BINDING | INFERENCE | ASSUMPTION | HYPOTHESIS | UNKNOWN

Certification:
PASS | FAIL | OPEN | BLOCKED | PROVISIONAL | AUDIT_ONLY | NONCANONICAL | CANDIDATE_NOT_IDENTITY | UNRESOLVED | SUPERSEDED

## Geometry
A trajectory requires >=2 valid spatial observations.
RAW source geometry outranks standardized signatures for provenance.
Density-cluster output is discovery only. Canonical recurrent geometry requires parameter stability and pairwise/complete-link closure.

## Interpretation gates
Shared airport != shared mission.
Proximity != coordination.
Co-route != common tasking.
Recurrent geometry != mission semantics.
Infrastructure intersection != targeting.
Owner != operator.
Callsign != airframe.

## V4 promoted analytical candidate
N196DM <-> N407PR, 2025-09-12:
REPEATED_AIRBORNE_CO_ROUTE_CANDIDATE.
Mission and coordination remain UNKNOWN.

## Blocked vectors
- N2JJ raw-source lineage.
- Complete authoritative islandwide electrical-grid denominator for N5854Z infrastructure testing.
- HBAL123/HBAL124/N519HB/N257TH one-to-one identity closure.

V4 artifacts remain external evidence inputs; importing them must preserve their hashes, lineage, contradictions, exclusions, and certification state.
