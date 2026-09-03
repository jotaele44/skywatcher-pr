# BQN Entity Delta Ledger v1

## Scope

This update records entities visible in a user-provided Flightradar24 replay screenshot at Rafael Hernández International Airport (BQN/TJBQ) on 2026-07-19 at 11:26 AST. It separates direct screenshot observations from tenant, lease, operator, and basing inferences.

## Delta

| Entity | Classification | Repository action | Confidence | Current finding |
|---|---|---:|---:|---|
| Aviación del Oeste | Aviation tenant candidate | Added | 0.72 | Aviation-linked map label in the west-apron commercial context; tenant and lease status unresolved. |
| Charlie Car Rental | Airport-support candidate | Added | 0.78 | Airport-adjacent commercial map label; no evidence of aviation tenancy or apron access. |
| N440TT | Transient aircraft | Added | 0.91 | Screenshot supports one SIG→BQN arrival event; basing, ownership, operator, and recurrence unresolved. |
| Air Puerto Rico Corp | Existing aviation operator | Preserved | 0.90 | Existing repository entity retained without adding a tenant or hangar conclusion. |

## Tenant-probability matrix

| Entity | Airport-area presence | Aviation function | Specific hangar linkage | PRPA lease corroboration | Tenant assessment |
|---|---:|---:|---:|---:|---|
| Aviación del Oeste | High | Moderate–high | Low | None located | Candidate only |
| Charlie Car Rental | High | Low | None | None located | Airport-support business, not an aviation-tenant finding |
| Air Puerto Rico Corp | High | High | Low | None located in this pass | Existing operator; tenancy unresolved |
| N440TT | Event-confirmed | Aircraft | None | Not applicable | Transient until recurrence is demonstrated |

## Verification results

### Business registry

No authoritative corporate-registry result was located during this pass for Aviación del Oeste or Charlie Car Rental. Both remain unresolved rather than negatively identified.

### FAA registration

The screenshot identifies N440TT as a Robinson R44 Raven II. An exact authoritative FAA record was not resolved during this pass, so owner and operator fields remain unset.

### PRPA leases and airport function

PRPA publicly describes BQN as supporting passenger and cargo operations, federal agencies, air-rescue training, airline maintenance, and commercial-asset development. No public lease or tenant document linking the candidate businesses to a particular BQN parcel or hangar was located in this pass.

### Hangar location

The screenshot places the labels within or adjacent to the west-side airport commercial/apron cluster. It does not resolve building footprints, lease parcels, controlled-access boundaries, or hangar numbers.

### Recurring BQN events

Only one dated N440TT arrival event is represented. Promotion to a recurring-aircraft candidate requires at least two additional independently dated BQN observations plus registration/model confirmation.

## Evidence discipline

- **T3:** User-provided FR24 screenshot and visible map labels.
- **T2:** Existing repository reference for Air Puerto Rico Corp and PRPA's official airport-function description.
- No T1 technical flight export, authoritative lease instrument, parcel record, or exact FAA registration record was added.

## Guardrails

1. Map labels are locational clues, not authoritative tenant records.
2. Airport-area presence does not imply controlled-ramp access.
3. A single arrival does not establish permanent basing or recurrence.
4. No anomalous, coordinated, covert, or causal interpretation is introduced.
