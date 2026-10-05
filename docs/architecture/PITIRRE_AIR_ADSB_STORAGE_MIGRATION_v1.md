# PITIRRE AIR ADS-B + Core Storage Migration v1

**State:** PASS / CLAIM_SCOPED  
**Branch:** `pitirre/repo-map-v1`  
**Frozen source census:** `main@2100e6527d49abc302b804d3175feea9ce614eb4`  
**Prior certified foundation head:** `a46850b5fd7ee5ee8a51556521e5b4caf5a653bd`

## Scope

This slice promotes nine previously classified `MOVE` rows without altering
the frozen 1,363-file source denominator.

### AIR.AVIATION ADS-B

- `adsb/__init__.py`
- `adsb/config.py`
- `adsb/models.py`
- `adsb/providers/__init__.py`
- `adsb/providers/base.py`
- `adsb/providers/opensky.py`
- `adsb/sink.py`

Canonical target:
`src/pitirre/domains/air/aviation/adsb/`.

### Core FR24-lineage persistence

- `src/skywatcher/fr24/database.py`
- `src/skywatcher/fr24/database_migrations.py`

Canonical target:
`src/pitirre/core/storage/fr24/`.

The storage namespace retains FR24 lineage in its path while ownership moves to
Core. Master Flight Log authority and source-manifestation semantics are not
changed.

## Adjudicated architecture refinement

The frozen manifest already targeted `src/pitirre/core/storage/fr24/`, but
`core/storage/` was omitted from the human-readable topology tree. The map is
corrected additively. This is a sequence/topology refinement, not a fifth domain,
new analytical owner, or Lens Realignment.

## Parity requirements

- legacy ADS-B public objects are identical to canonical objects;
- legacy module aliases resolve to the canonical config/model/provider/sink modules;
- canonical OpenSky/provider behavior remains covered by the existing mocked tests;
- canonical ADS-B sink writes through canonical Core storage;
- legacy and canonical FR24 database modules are one logical implementation;
- schema path and repository-root resolution remain unchanged logically;
- migration 0001/0002/0003 order, idempotence and FK behavior remain unchanged;
- root ADS-B compatibility paths contain no duplicate implementation definitions;
- root ADS-B shims are classified as the physical `domain` bucket for boundary checks;
- all existing Skywatcher CI, GUI, federation, security and desktop gates remain green.

## Invariants

- `SOURCE_MANIFESTATION != OBSERVATION != EVENT != ENTITY`;
- ADS-B position availability does not prove aircraft identity;
- callsign/registration normalization does not prove identity;
- ADS-B observation does not imply mission or intent;
- FR24 datastore lineage does not make FR24 ingest the owner of shared persistence;
- MFL authority remains unchanged;
- frozen source blob SHA/size values remain provenance evidence.

## Verification

Verification basis: `3ff7a084dee5149b9014b9b91bf176cfdfa2822b`.

All registered PR #341 workflows completed successfully on that exact head:
Skywatcher CI (Python 3.10/3.11/3.12, frontend, lint, lock, ADS-B and imagery),
GUI capability parity + GUI Reachability E2E, Federation Compatibility, HAF,
Admin Control Plane Boundary, SATIM Phase 2/runtime, pip-audit, Secret Scan,
CodeQL, federation template drift, and desktop builds on Windows/macOS/Linux.

The explicit parity firewall proves:

- root ADS-B facade objects resolve to the canonical AIR.AVIATION objects;
- module-alias files resolve to the canonical modules rather than duplicate logic;
- canonical ADS-B sink writes through the canonical Core storage contract;
- historical SkyWatcher FR24 database modules alias the canonical Core modules;
- repository/schema path calculations still resolve to the same repository assets;
- migrated root files contain no duplicate class/function implementations.

## Certification boundary

PASS is claim-scoped to these nine rows. It does not certify complete AIR,
complete Core, MFL/corpus migration, FR24 ingest migration, repository rename,
or compatibility-wrapper retirement.
