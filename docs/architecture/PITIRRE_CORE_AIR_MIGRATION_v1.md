# PITIRRE Core + AIR Migration v1

**State:** CANDIDATE_PENDING_CI  
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

Promotion to PASS must use the exact final branch head after all changes.
