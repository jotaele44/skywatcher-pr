# PITIRRE Core + AIR Migration v1

**State:** PASS / FOUNDATION_ONLY  
**Branch:** `pitirre/repo-map-v1`  
**Parent census:** `main@2100e6527d49abc302b804d3175feea9ce614eb4`  
**Parent contradiction closure:** PR #341 / `bc842858a0ce97b97627b2fedde201aeebc8f7e4`

## Scope

This is the first physical implementation slice of the repository map. It does
not rename the repository and does not alter the frozen 1,363-file source census.

Three previously classified implementations receive canonical PITIRRE paths:

| Frozen source path | Canonical path | Ownership |
|---|---|---|
| `src/skywatcher/core/domain_registry.py` | `src/pitirre/core/domains/registry.py` | Core |
| `src/skywatcher/core/pitirre_observation.py` | `src/pitirre/core/contracts/observation.py` | Core |
| `src/skywatcher/normalizers/air_event_normalizer.py` | `src/pitirre/core/normalization/air_event.py` | Core / AIR-scoped |

Historical paths remain wrappers. A second explicit compatibility surface lives
under `src/pitirre/compat/skywatcher/`.

## AIR package

`src/pitirre/domains/air/` instantiates the four registry-defined AIR
subdomains: AVIATION, AIRSPACE, AEROSTAT and ATMOSPHERIC_SENSOR. The domain
facade delegates normalization/validation to Core and contains no duplicated
analytical logic.

## Invariants

- source census denominator remains 1,363;
- historical blob identities remain source-snapshot evidence;
- old import path != independent implementation;
- compatibility wrapper != canonical authority;
- missing geometry != geographic zero;
- source label != inferred mission;
- physical domain != analytical owner;
- Core cannot import SATIM/FPIM/CORRIM/Legacy;
- AIR cannot bypass Core to consume analytical implementation code.

## Required gates

- old/new/compat import identity parity;
- domain registry parity;
- observation adapter parity;
- AIR normalization + schema parity;
- module-boundary enforcement including the physical-domain bucket;
- Python 3.10/3.11/3.12 tests;
- Ruff + frontend + federation/GUI regression gates;
- coverage ratchet with `src/pitirre` included.

## Verification

Code/behavior verification basis: `d955195f9bb17ce0d2d480a922915c4416578a83`.

All registered PR #341 workflows completed successfully on that exact code
head: Skywatcher CI (Python 3.10/3.11/3.12, frontend, lint, lock, imagery,
ADS-B), GUI capability parity + reachability E2E, Federation Compatibility,
HAF, Admin Control Plane, SATIM Phase 2/runtime, pip-audit, Secret Scan,
CodeQL, federation template drift and desktop builds on Windows/macOS/Linux.

One compatibility regression was found during the first run:
`skywatcher.core.spacetrack.pitirre_adapter` imports the historical private
helper `_envelope`. The wrapper initially omitted it. The final implementation
preserves `_envelope` as an alias to the canonical helper and has a permanent
regression assertion.

## Certification boundary

PASS is limited to this foundation slice. It certifies the three migrated
implementation rows, compatibility identity, the AIR package/subdomain
foundation and the stated regression gates. It does not certify complete Core
migration, complete AIR migration, repository rename, wrapper retirement, MFL
migration, or any SATIM/FPIM/CORRIM physical move.
