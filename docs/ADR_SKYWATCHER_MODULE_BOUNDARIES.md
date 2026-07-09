# ADR: Skywatcher Module Boundaries (Core / SATIM / FPIM / CORRIM)

## Status

Accepted.

## Decision

Skywatcher's internal logic is organized into four explicit boundaries:

- **Core** — orchestration, runtime contracts, and shared static registries
  (readiness/ontology gating, normalization helpers, known-operator and
  airspace-footprint reference data, geometry and visual-detection
  primitives). Importable by anyone; imports only stdlib/third-party.
- **SATIM** — terrain and imagery context only (screenshot/satellite
  calibration, tile-seam/boundary classification). Imports Core; must not
  import FPIM or CORRIM.
- **FPIM** — flight path and behavior context only, including tracing a
  flight path against a static POI (point of interest) gazetteer — any
  geographical point, natural or manmade, of interest to humans, regardless
  of the POI's relevance/correlation to the aircraft. Imports Core; must not
  import SATIM or CORRIM.
- **CORRIM** — correlation scoring and evidence fusion only. The *only*
  module permitted to combine SATIM's and FPIM's outputs.

A fifth bucket, **legacy**, quarantines pre-existing logic that performs
intent/purpose inference. It is importable only via its own backward-compat
shim and must never be imported by Core/SATIM/FPIM/CORRIM.

The boundary is enforced by a manifest (`src/skywatcher/core/module_boundaries.py`)
and a stdlib-`ast`-based test (`tests/test_module_boundaries.py`) — no new
dependency was introduced (see Rejected Options).

## Rationale

This reorg was prompted by three concrete, pre-existing cross-boundary
imports discovered by tracing the actual import graph (not just the file
layout), plus one pre-existing intent-inference module that contradicts the
codebase's own evidence-preservation posture:

1. `satim_geometry.py` (terrain/imagery) imported `haversine_m` from
   `skywatcher.correlation.footprint_proximity` — a generic geodesy helper
   embedded in what became FPIM/CORRIM territory. Fixed by promoting
   `haversine_m`/`EARTH_RADIUS_M` to `skywatcher.core.geo_utils`.
2. `fr24/calibration/l2_route_calibration.py` (SATIM) imported
   `COLOR_RANGES`/`MIN_ROUTE_PIXELS` from `fr24.route_extractor` (FPIM)
   inside a `try/except` with a duplicated hardcoded fallback — a latent bug
   masking import failures. Fixed by promoting the constants to
   `skywatcher.core.route_visual_constants` and dropping the duplicate
   fallback.
3. `fr24/calibration/l4_registry_audit.py` (SATIM) imported `KNOWN_OPERATORS`
   from `aircraft_intelligence` (FPIM). Fixed by promoting the dict to
   `skywatcher.core.known_operators`.
4. `aircraft_intelligence.py`'s `FlightMissionAnalyzer._deduce_mission()`
   performs heuristic "why is this flying" mission scoring (callsign +
   duration + altitude + speed against named mission categories). This
   contradicts `pipeline/rlsm_ontology_gate.py`'s `do_not_assume_intentional`
   guardrail, `skywatcher.fusion`'s `operational_cueing: False` posture, and
   the explicit requirement that no module in this pipeline infer intent or
   operational purpose. It is unused anywhere else in the repository, making
   it low-risk to quarantine rather than delete (preserving backward
   compatibility for the existing import path).

Each of the first three violations followed the same shape: a
domain-neutral shared primitive (a math function, a color-threshold table, a
ground-truth dict) had been embedded inside a domain module it didn't belong
to. In every case the fix was to promote the primitive to Core and have both
sides import it from there — never from each other.

**Known, narrow, intentional exception**: `skywatcher.core.readiness_engine`
reads SATIM's calibration status report
(`fr24/calibration/readiness_adapter.py`) to fold it into Core's own
readiness aggregation contract, alongside the PRII integration report. This
is a "consume a status artifact for aggregation" relationship — Core reading
a domain's summary status, the same way it already reads
`integration_report.json` — not a "combine evidentiary outputs" relationship.
CORRIM's exclusive role remains combining SATIM's and FPIM's *analytical*
outputs (imagery findings + flight-path/POI evidence) for correlation
scoring. This exception is recorded explicitly in
`MODULE_IMPORT_EXCEPTIONS` and enforced (not silently allowed) by the
boundary test.

**POI clarification**: a POI is any geographical point, natural or manmade,
of interest to humans — independent of whether it turns out to be relevant
to a given aircraft. FPIM's job is to trace a flight path and enumerate
every POI along or near it, unfiltered; `src/skywatcher/correlation/footprint_proximity.py`
was reclassified from an earlier CORRIM assignment into FPIM once tracing
its actual imports confirmed it only matches path points against a static
gazebo/footprint reference (`skywatcher.registry.airspace_footprints`, now
Core) and never touches SATIM's imagery output. CORRIM's role is unchanged:
it is the only module that would combine that FPIM output with SATIM's
imagery-derived findings.

## Required Sequence

1. **Core extraction** — move orchestration/contract logic
   (`prii_readiness_engine.py`, `pipeline/rlsm_ontology_gate.py`,
   `pipeline/normalize_*.py`, `pipeline/db_utils.py`) into
   `src/skywatcher/core/`, with backward-compat shims left at the old paths.
   Extract `KNOWN_OPERATORS` and FR24 color constants into Core so later
   phases can depend on them cleanly.
2. **SATIM boundary fixes** — fix the three cross-boundary imports above; no
   files physically move; SATIM's bucket is registered in the manifest.
3. **FPIM extraction + quarantine** — move `AircraftProfile`/
   `AircraftIntelligence` into `src/skywatcher/fpim/aircraft_profile.py`;
   quarantine `MissionAnalysis`/`FlightMissionAnalyzer`/`analyze_all_aircraft`
   into `src/skywatcher/legacy/quarantined_mission_inference.py`; shim
   `aircraft_intelligence.py`; reclassify `footprint_proximity.py` into FPIM.
4. **CORRIM consolidation** — move `gis_intelligence.py`,
   `ilap_airspace_bridge.py`, `aasb_airspace_bridge.py` into
   `src/skywatcher/corrim/`, with shims; `skywatcher.fusion` classified
   in place (already clean).
5. **Boundary enforcement, specs, schemas** — add the `ast`-based boundary
   test, module spec docs, and additive JSON Schema contracts for each
   module's output envelope.

## Rejected Options

### Full physical relocation of every SATIM/FPIM file

Rejected. `fr24/calibration/**` and the FPIM-classified `fr24/*.py` files
were already internally cohesive and did not (after the three fixes above)
violate the boundary. Moving ~90 files into new packages would be high
mechanical churn for no architectural benefit, and works against
"adapters over rewrite." They are classified via the manifest instead.

### Deleting `FlightMissionAnalyzer`/`_deduce_mission()` outright

Rejected. This would break backward compatibility for the existing
`aircraft_intelligence.FlightMissionAnalyzer` import path, violating the
requirement to preserve all existing functionality. Quarantining it
(moving it, unchanged, behind an explicit "do not use" module, still
reachable via the old import path) satisfies both the no-intent-inference
requirement for FPIM's *active* surface and backward compatibility.

### Adopting `import-linter` or `grimp` for boundary enforcement

Rejected. Neither is a dependency anywhere in this repo (`pyproject.toml`,
`tools/*/pyproject.toml`), and introducing one for a ~150-line rule set is
unnecessary. A stdlib-`ast`-based test keeps the same "stdlib-only" ethos
already used elsewhere in the codebase (e.g. `fr24/`'s own calibration
harness) and needs no new install step in CI.

## Consequence

```text
SATIM ──┐
        ├──> Core <──┐
FPIM  ──┘            │
                      │
SATIM, FPIM ────> CORRIM   (the only module combining SATIM + FPIM outputs)

legacy (quarantine) <──  aircraft_intelligence.py shim only
                          (no core/satim/fpim/corrim module may import it)
```

Everything else — CI, `federation.json.hub_callable_commands`, existing
import paths, existing tests — continues to work unchanged; the boundary is
additive scaffolding around already-working code, not a rewrite of it.
