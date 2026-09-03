# Module Spec: Core

## Role

Orchestration, runtime contracts, and shared static registries. Core is
importable by every other bucket (SATIM, FPIM, CORRIM); it must not import
from any of them (one narrow, explicit exception below).

## In scope

| Path | Responsibility |
|---|---|
| `src/skywatcher/core/readiness_engine.py` | Aggregates PRII gate + calibration reports into a readiness verdict (`prii_readiness_report.json`). |
| `src/skywatcher/core/ontology_gate.py` | Fails-closed gate enforcing evidence-preservation rules (`do_not_assume_intentional`, `preserve_raw_label`, etc.) over config/vocab registries. |
| `src/skywatcher/core/normalize_locations.py` | Alias-based location/airport/LZ/hangar normalization. Preserves raw text; never invents names. |
| `src/skywatcher/core/normalize_missions.py` | Alias-based mission/behavior/blackout normalization. Returns `UNKNOWN` rather than guessing. |
| `src/skywatcher/core/normalize_operators.py` | Alias-based aircraft-identity/operator normalization. |
| `src/skywatcher/core/db_utils.py` | SQLite connection configuration helper. |
| `src/skywatcher/core/known_operators.py` | `KNOWN_OPERATORS` — operator-provided ground truth per tail number (not inferred). Shared by SATIM and FPIM. |
| `src/skywatcher/core/route_visual_constants.py` | Shared FR24 pixel-color threshold table, used by both SATIM calibration and FPIM route extraction. |
| `src/skywatcher/core/geo_utils.py` | `haversine_m` — generic great-circle distance helper. |
| `src/skywatcher/registry/airspace_footprints.py` | `AirspaceFootprint` — static POI/footprint gazetteer loader (CSV). Shared reference data, same role as `known_operators.py`. |
| `src/skywatcher/core/module_boundaries.py` | The boundary manifest itself (this spec's source of truth). |

## Out of scope

- Any classification of imagery/terrain content (SATIM).
- Any flight-path/behavior detection or POI-proximity scoring (FPIM).
- Any combination of SATIM and FPIM outputs (CORRIM).
- Intent/purpose inference of any kind (see `docs/MODULE_SPEC_FPIM.md`'s
  quarantine note).

## Known exception

`readiness_engine.py` reads SATIM's calibration status report
(`fr24/calibration/readiness_adapter.py`) to fold it into its own readiness
contract — a "consume a status artifact for aggregation" relationship, not a
"combine evidentiary outputs" relationship (that remains CORRIM's exclusive
role). Recorded explicitly in `MODULE_IMPORT_EXCEPTIONS` and enforced by
`tests/test_module_boundaries.py`. See
`docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md` for the full rationale.

## Backward compatibility

`prii_readiness_engine.py`, `pipeline/rlsm_ontology_gate.py`,
`pipeline/normalize_locations.py`, `pipeline/normalize_missions.py`,
`pipeline/normalize_operators.py`, and `pipeline/db_utils.py` at their
original paths are thin re-export shims over the modules above.
