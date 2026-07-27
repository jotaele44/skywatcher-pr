# Module Spec: FPIM

## Role

Flight path and behavior context only. FPIM resolves aircraft identity,
extracts/vectorizes flight tracks, fuses multi-screenshot observations of the
same aircraft, and traces a flight path against a static POI (point of
interest) gazetteer. It contains no terrain-classification logic. It imports
Core; it must not import SATIM or CORRIM.

## In scope

| Path | Responsibility |
|---|---|
| `src/skywatcher/fpim/aircraft_profile.py` | `AircraftProfile`, `AircraftIntelligence` — N-number to owner/operator lookup and profile enrichment. |
| `fr24/route_extractor.py` | FR24 route-color/aircraft-icon extraction from screenshots. |
| `fr24/track_vectorizer.py` | Route-candidate to track-feature vectorization. |
| `fr24/flight_fusion.py` | Same-flight multi-screenshot fusion into one multi-point record. |
| `fr24/wave_validator.py` | Temporal-wave validation against vectorized tracks. |
| `fr24/endpoint_matcher.py` | Nearest-airport / endpoint matching for fused waves. |
| `src/skywatcher/correlation/footprint_proximity.py` | **POI tracing** (see below). |

## POI tracing (in scope, exhaustive and unfiltered)

FPIM is responsible for tracing the flight path against static geographic
reference data (`skywatcher.registry.airspace_footprints`, via
`correlate_point_to_footprints()`) and enumerating **every** POI — any
geographical point, natural or manmade, of interest to humans — along or
near the path, regardless of the POI's actual relevance or correlation to
the aircraft, and regardless of any flight-behavior label. This is distinct
from label-independence (below), which governs *whether* a track is
analyzed at all: POI enumeration must be exhaustive, not selective. FPIM
does not score or interpret a POI's significance relative to imagery/terrain
evidence — that scoring is CORRIM's job, consuming FPIM's POI-proximity
output alongside SATIM's imagery findings.

`footprint_proximity.py` was reclassified here from an earlier CORRIM
assignment once tracing its actual imports confirmed it is a pure
static-gazetteer-vs-point match with no SATIM imagery dependency — see
`docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md`.

## Label independence (in scope, normative rule)

FPIM's trajectory/behavior detection (loiter patterns, corridor entry,
repeat passes, multi-frame fusion) must operate on observed trajectory
characteristics alone. It must never branch on callsign, known-operator, or
mission label to decide *whether* a track gets analyzed — labeled and
unlabeled/unknown tracks are processed identically. Verified by
`tests/test_fpim_label_independence.py`.

## Out of scope

- Terrain/imagery classification (SATIM).
- Correlation scoring or fusing FPIM output with SATIM findings (CORRIM).
- Any inference of *why* an aircraft is flying (intent/mission/purpose
  guessing) — see Quarantine below.

## Quarantine: `skywatcher.legacy.quarantined_mission_inference`

`FlightMissionAnalyzer`/`_deduce_mission()`/`MissionAnalysis`/
`analyze_all_aircraft` are **permanently out of scope** for FPIM's active
API. They perform heuristic mission/intent deduction from callsign +
duration + altitude + speed, which the pipeline's requirements explicitly
forbid. They are quarantined in `skywatcher.legacy` for backward
compatibility with the pre-existing `aircraft_intelligence.FlightMissionAnalyzer`
import path only, and must not be reintroduced into FPIM. Enforced by
`tests/test_fpim_quarantine.py`.

## Active fallback behavior

`AircraftIntelligence._deduce_profile()` resolves only observable identity
fields from callsign prefixes and stored flight metadata. Aircraft type,
route geometry, time, speed, altitude, and proximity do not establish why an
aircraft is flying, so unresolved `primary_mission` values remain `Unknown`.
`AIRCRAFT_TYPE_MISSIONS` is retained as an empty compatibility constant.
Source-declared roles from the curated operator registry remain available and
are labeled as source-declared in reports.

## Backward compatibility

`aircraft_intelligence.py` at its original path is a compatibility facade for
`AircraftProfile`, `AircraftIntelligence`, `KNOWN_OPERATORS`, and
`CALLSIGN_PREFIXES`. Quarantined inference symbols remain lazily reachable for
legacy callers but are excluded from `__all__` and emit `DeprecationWarning`.
No active Core, SATIM, FPIM, or CORRIM module imports the quarantine package.
