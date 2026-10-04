# PITIRRE Repository Map v1 — Live Census Freeze

**State:** CANDIDATE_BINDING / AUDIT_ONLY  
**Source repository:** `jotaele44/skywatcher-pr`  
**Stable GitHub repository ID:** `1261399537`  
**Frozen live baseline:** `main@2100e6527d49abc302b804d3175feea9ce614eb4`  
**Tree completeness:** PASS — recursive tree returned truncated=false  
**File denominator:** 1363

## Purpose

This artifact freezes the target PITIRRE repository topology and binds it to an
exhaustive file-level disposition census in
`manifests/pitirre_path_disposition.v1.csv`.

The census is a migration plan, not evidence that files have already moved.
No historical SkyWatcher provenance is rewritten by this branch.

## Canonical axes

```text
PHYSICAL DOMAIN: AIR | LAND | WATER | SPACE
ANALYSIS OWNER : CORE | RLSM | SATIM | FPIM | CORRIM
```

`ROAD` is not a fifth top-level domain. Its canonical path is
`LAND.TRANSPORT.ROAD`.

Analysis ownership and physical-domain scope are independent. A CORRIM
association may therefore have `domain_scope=[AIR,LAND]` while
`analysis_owner=CORRIM`.

## Canonical target topology

```text
src/pitirre/
├── core/
│   ├── contracts/
│   ├── domains/
│   ├── provenance/
│   ├── evidence/
│   ├── identity/
│   ├── temporal/
│   ├── spatial/
│   ├── normalization/
│   ├── knowledge/
│   ├── replay/
│   ├── registries/
│   ├── readiness/
│   ├── governance/
│   └── federation/
├── domains/
│   ├── air/
│   │   ├── aviation/
│   │   ├── airspace/
│   │   ├── aerostat/
│   │   └── atmospheric_sensor/
│   ├── land/
│   │   ├── terrain/
│   │   ├── facility/
│   │   ├── infrastructure/
│   │   ├── transport/{road,rail,trail,other_network}/
│   │   ├── vehicle/
│   │   ├── construction/
│   │   ├── sensor/
│   │   └── field_activity/
│   ├── water/{hydrologic,coastal,maritime}/
│   └── space/{orbital,satellite,launch,reentry,remote_sensing,space_weather,ground_segment}/
├── pipelines/rlsm/
├── analysis/{satim,fpim,corrim}/
├── services/
├── api/
├── cli/
└── compat/skywatcher/

apps/{web,desktop,ios}/
schemas/
configs/
manifests/
exports/
tests/
fixtures/
docs/
skills/
scripts/
legacy/skywatcher/
```

## Domain ownership

### AIR
Owns aviation, airspace, aerostat and atmospheric-sensor observations/state.
The Master Flight Log remains the flight-history authority. Registration,
callsign, proximity, count equality and nearest-only evidence do not prove
airframe or flight-event identity.

### LAND
Owns terrain, facilities, infrastructure, transport networks, vehicles,
construction, terrestrial sensors and field observations. ROAD is represented
as `LAND.TRANSPORT.ROAD`; adjacency, intersection and proximity do not prove
connectivity or access.

### WATER
Owns hydrologic, coastal and maritime observations. PITIRRE does not duplicate
AguaYLuz water-system authority. Missing coordinates remain NULL/NONE/UNRESOLVED
and must never silently become (0,0).

### SPACE
Owns orbital, satellite, launch, reentry, remote-sensing source, space-weather
and ground-segment observations. Source/platform/product provenance for remote
sensing is SPACE; image interpretation remains SATIM.

## Analytical ownership

- **CORE:** shared contracts, provenance, evidence axes, identity, temporal and
  spatial references, registries, replay, readiness and certification primitives.
- **RLSM:** source inventory, hashing, OCR/visible extraction, pixel geometry,
  localization, immutable extraction receipts and review queues.
- **SATIM:** imagery/terrain interpretation, artifact assessment, registration,
  image quality, multi-epoch and cross-source image tests.
- **FPIM:** track reconstruction, trajectory measurements, recurrence,
  endpoint candidates and neutral POI proximity.
- **CORRIM:** cross-domain spatial/temporal association, null testing,
  contradiction reconciliation and review integration.
- **LEGACY:** compatibility/quarantine only; may not supply new canonical facts.

## File-level census results

| Disposition | Files |
|---|---:|
| DELETE_AFTER_PARITY | 2 |
| MOVE | 818 |
| QUARANTINE | 64 |
| RETAIN | 439 |
| WRAP | 40 |
| UNRESOLVED | 0 |

**UNRESOLVED residue:** 0 file(s).  
**DELETE_AFTER_PARITY candidates:** 2 file(s), placeholder-only unless separately adjudicated.

Every file in the frozen 1363-file denominator appears exactly once in
the CSV manifest. The manifest includes current blob SHA, byte size, owner,
physical-domain scope, disposition, target path, execution gate and rationale.

## Disposition semantics

- `RETAIN`: keep current path; usually immutable schema/history/provenance,
  federation contract, CI surface, or stable repository metadata.
- `MOVE`: canonical target exists, but move only after import/behavior/test
  parity and a compatibility path where required.
- `WRAP`: retain current path as compatibility interface while canonical code
  lives at the target.
- `QUARANTINE`: preserve but exclude from active canonical findings.
- `DELETE_AFTER_PARITY`: deletion is permissible only after the named gate;
  currently limited to empty runtime placeholders.
- `UNRESOLVED`: no deterministic promotion; manual adjudication required.

## Hard invariants

1. Repository rename does not change repository identity.
2. Historical SkyWatcher artifacts are not globally renamed.
3. Existing versioned schemas remain readable and immutable; new semantic
   versions are additive.
4. MFL/corpus source manifestations remain separate from analytical flights.
5. Spiderweb remains geometry authority; PITIRRE stores references and temporal
   state rather than silently claiming authority.
6. AguaYLuz remains hydrologic/water-system authority where applicable.
7. `SOURCE_MANIFESTATION != OBSERVATION != EVENT != ENTITY`.
8. RLSM extraction does not promote semantic interpretation.
9. SATIM does not own flight behavior.
10. FPIM does not own imagery interpretation.
11. CORRIM association is not causation.
12. Legacy code cannot become a new active evidentiary dependency.
13. Migration 0004 / cumulative implication production activation remains
    governed by its independent gates.
14. No active file is deleted simply because the target layout is cleaner.

## Migration order

1. Freeze this census.
2. Close every `UNRESOLVED` row.
3. Establish PITIRRE Core contracts and compatibility namespace.
4. Migrate AIR without altering MFL authority.
5. Promote SPACE source families and adapters.
6. Introduce LAND contracts, especially transport-network state.
7. Expand WATER adapters without duplicating AguaYLuz.
8. Separate RLSM physically from analytical modules.
9. Migrate SATIM, FPIM and CORRIM behind old-path wrappers.
10. Migrate API/GUI/apps and enforce registry-driven navigation.
11. Run old/new import, behavior, schema, GUI and federation parity.
12. Rename repository only as a late explicit stage.
13. Retire wrappers only after dependency exhaustion and regression PASS.

## Certification boundary

This document certifies only that the recursive Git tree was completely
enumerated and deterministically classified under the stated rules. It does
**not** certify that proposed target files exist or that migration has occurred.
The v1 census has **zero avoidable UNRESOLVED file rows**; execution remains gated
by the per-row migration conditions and the contradictions below.


## Contradictions discovered during census

### PITIRRE-C001 — GEOMETRY — RESOLVED

`src/skywatcher/normalizers/air_event_normalizer.py` currently calls its
generic float converter for latitude and longitude with the converter's default
value of `0.0`. Missing/blank coordinates can therefore become `(0,0)`
instead of NULL/NONE/UNRESOLVED.

**Impact:** silent spatial false-positive risk. Proximity, spatial joins,
cross-domain overlap and map placement can succeed incorrectly.

**Resolution:** PASS. Missing/invalid coordinates now remain nullable with
explicit geometry state and raw source-coordinate preservation; legitimate zero
coordinates remain valid. Cross-domain overlap skips unresolved/invalid
geometry. The former `BLOCKED_GEOMETRY_NULL_SEMANTICS` gate is closed by the
regressions verified on PR #341 at `b5f8c607c2fa347276cbfe438ba0f8e0dbcf4b8b`.

### PITIRRE-C002 — CLASS/GOVERNANCE — RESOLVED

The July module-boundary revision permits evidence-gated speculative mission
classification, while active ontology v2.1 explicitly keeps mission or intent
inference prohibited. `src/skywatcher/fr24/mission_classification.py` is
therefore classified as compatibility/quarantine for PITIRRE.

**Resolution:** PASS. Ontology v2.1 controls; the July speculative-mission
permission is SUPERSEDED. Active mission/intent inference is removed from FPIM,
CORRIM, routing, federation export, API normalization and GUI presentation;
Legacy replay remains explicitly noncanonical. The
`NO_MISSION_PROMOTION` gate is now enforced and passed on PR #341 at
`b5f8c607c2fa347276cbfe438ba0f8e0dbcf4b8b`.

## Post-freeze adjudication receipt

The 1,363-file denominator remains the immutable source census at
`main@2100e6527d49abc302b804d3175feea9ce614eb4`. The implementation branch is
a later state and is not retroactively inserted into that denominator.

C001/C002 were repaired and regression-gated on PR #341. At verification
basis head `b5f8c607c2fa347276cbfe438ba0f8e0dbcf4b8b`, Skywatcher CI, GUI parity/E2E, federation,
security/governance gates, CodeQL and all three desktop-platform builds passed.
This closes only the two contradiction prerequisites; physical Core/AIR
migration and repository rename remain separate later vectors.

## Census closure

```text
SOURCE FILES        = 1363
CLASSIFIED FILES    = 1363
UNRESOLVED FILES    = 0
ROW CONSERVATION    = 1363 = 1363 + 0
TREE TRUNCATED      = false
```

The classification denominator is closed for this source snapshot. This is
**bounded exhaustion of the Git tree at the frozen SHA**, not universal
exhaustion of runtime/operator-local data or future branch content.
