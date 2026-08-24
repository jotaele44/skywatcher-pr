# Analysis lens registry

How to add an analytical parameter, lens, or rule to Skywatcher without writing Python.

## What this replaced

Adding an analytical parameter used to mean editing code in several places and hoping
they stayed in sync. Concretely, before this existed:

- **Five artifact vocabularies** meant roughly the same thing and mapped to each other
  nowhere: the `SATIM-A01..A12` taxonomy, the 18-value `observation_class` enum,
  `ArtifactSignal`, `tile_artifact.artifact_class`, and
  `tile_artifact_ledger.artifact_class`.
- **~13 detector modules** at repo root shared one implicit interface (`Signal` enum →
  `SIGNAL_WEIGHTS` → `Observation` → `score_*`) and were registered nowhere. Only 2 of
  the 12 taxonomy classes were reachable by automation.
- **Thresholds were bare literals inside function bodies** — `0.65 * ratio_component +
  0.35 * confidence_component`, band cutoffs `.80/.60/.40`, `SEAM_SCORE_THRESHOLD = 6.0`.
- **Nothing recorded which checks ran.** A check skipped for a missing input and a check
  that ran and found nothing produced identical output.

## The model

| Concept | What it is | Where it lives |
|---|---|---|
| **Parameter** | One input a lens needs, and what is lost if it is absent | inside a lens file |
| **Lens** | One analytical objective, owned by exactly one domain | `configs/analysis/lenses/*.yaml` |
| **Objective profile** | The set of lenses a run must satisfy | `configs/analysis/objectives/*.yaml` |
| **Threshold** | A governed numeric cutoff with a status | `docs/architecture/SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv` |
| **Coverage** | Per-run record of what ran, degraded, or could not run | emitted as `coverage_report.json` |

Code lives in `src/skywatcher/core/lenses/`. It is Core-owned because `satim` and `fpim`
may import `core` but not each other (ADR v2.0 §3.1), and both stages need it.

## Adding a lens

Drop a YAML file in `configs/analysis/lenses/`. Minimum viable lens:

```yaml
lens_id: satim.my_lens          # <owner-ish prefix>.<name>, must be unique
name: Human readable name
owner: SATIM                    # Core | RLSM | SATIM | FPIM | CORRIM
stage: satellite_image_processing   # or flight_data_collection, cross_domain
status: experimental            # experimental | active | deprecated
version: 1.0.0
objective: One sentence on what question this lens answers.

required_parameters:
  - parameter_id: roi_target
    name: Target ROI
    kind: array                 # number|integer|string|boolean|enum|array|path
    description: What it is.

optional_parameters:
  - parameter_id: control_roi
    name: Control ROI
    kind: array
    required: false
    degraded_behavior: What analysis is lost when this is absent.

emits:
  - MY_FINDING_CANDIDATE

prohibited_claims:
  - What this lens must never assert.
```

Then run `pytest -q tests/test_analysis_lens_registry.py`. No code change is needed —
the registry loads the directory, and the `/analysis` page renders whatever it finds.

### Rules the loader enforces

These fail at load time, not halfway through a run:

- **An optional parameter must declare `degraded_behavior`.** An absent optional
  parameter has to produce a recorded degradation, never a silent fallback.
- **Only CORRIM may own a `cross_domain` lens** (ADR v2.0 §3) — it is the sole owner of
  SATIM–FPIM association.
- **Owner, stage, status, restriction, and evidence axes** must be known values.
- **A profile with no required lenses is rejected**, because it cannot gate anything.

### The YAML subset

`configs/analysis/*` is read by `load_simple_yaml`
(`src/skywatcher/core/normalize_locations.py`), a deliberate stdlib-only subset — Core
must not take a PyYAML dependency. Two limits matter:

- **No folded or literal scalars** (`>-`, `|`). Use one long line.
- **No `:` inside a list item.** A list item containing a colon parses as a mapping.

The first raises; the second mis-parses quietly. Both are easy to hit when writing prose
into `prohibited_claims`.

## Adding a threshold

Add a row to `SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv` with every ADR §12 field:
`threshold_id, owner, current_value, unit, purpose, status, validation_artifact,
failure_behavior, effective_version, supersedes`.

`status` controls whether it may execute:

| Status | Executable | Meaning |
|---|---|---|
| `VALIDATED`, `CANONICAL` | yes | Empirically supported |
| `EXECUTABLE_CANDIDATE` | yes | Running, not yet validated |
| `CANDIDATE`, `CANDIDATE_PROJECT_GATE` | no | Documented only |
| `PROHIBITED` | never | Must not run at all |

`ThresholdRegistry.value_of()` refuses anything not executable, with the reason. Every
executed threshold stamps `{threshold_id, value, status}` into output (ADR v2.1 A2), so a
consumer can always tell a candidate-grade cutoff from a validated one.

Reference a threshold from a lens via `threshold_ids:` or a parameter's `threshold_id:`.
A lens naming a nonexistent or non-executable threshold fails
`tests/test_analysis_lens_registry.py`.

## Coverage, and why runs fail closed

`evaluate_coverage()` returns a per-lens state:

| State | When |
|---|---|
| `SATISFIED` | Ran, all parameters supplied, produced a result |
| `DEGRADED` | Ran but an optional parameter was absent, or produced nothing |
| `MISSING` | A required parameter or input was unavailable |
| `NOT_APPLICABLE` | Declared inapplicable to this run |

**A required lens in any state but `SATISFIED` blocks run completion**, `DEGRADED`
included — the run did not meet its stated objective, and saying so is the point.
Marking a required lens `NOT_APPLICABLE` is deliberately not an escape hatch.

Every non-satisfied state carries a mandatory `reason`. "It didn't run" without a stated
cause is the outcome this record exists to prevent.

## The vocabulary crosswalk

`src/skywatcher/satim/artifacts/artifact_crosswalk_v1.json` is the single source for
artifact-class arbitration, restriction minima, auto-derivation, and cross-vocabulary
equivalence. It replaced six tables that encoded overlapping facts with nothing keeping
them in agreement.

Two things to know before editing it:

- **`arbitration_rank` is the real ordering**, not the taxonomy's `priority` integer —
  that field is non-unique (A02/A11 both 7, A04/A09 both 8) and so cannot define a total
  order. Rank is validated unique and dense at load.
- **The older vocabularies are coarser than SATIM-A.** `ZOOM_BLUR` and `BLUR_EDGE` name
  blur without its cause; `ORTHO_MOSAIC_BOUNDARY` conflates a seam with an
  orthorectification offset. Each is canonically assigned to one class with the
  conflation recorded under `vocabulary_ambiguous`, so a reviewer of a legacy record does
  not read more precision into the term than it carries.

Terms with no SATIM-A equivalent are listed under `deliberately_unmapped` with a reason.
That is a real answer, not a gap — do not force-map them to make the crosswalk look
complete. `tests/test_satim_artifact_crosswalk.py` requires every enum value to be either
mapped or explicitly unmapped, so adding a term anywhere forces a decision here.

## Governance

The ontology was unfrozen by ADR v2.1 (`docs/architecture/`), which also opened a
**bounded** facility-function channel: SATIM may emit `DUAL_USE_FUNCTION_CANDIDATE` only
as a Finding carrying the full §5.3 confidence record. Mission and intent inference remain
prohibited, and `mission_or_intent_inference_authorized` stays `false`.

The pre-unfreeze baseline is archived byte-identical under
`docs/architecture/archive/v2_0/` and hash-checked, so the frozen state stays provable and
a re-freeze remains possible. **Do not modify anything under that directory.**

## Where it surfaces

- `GET /api/analysis/registry` — lenses, objectives, thresholds
- `/analysis` in the dashboard — reachable from the sidebar
- Entities `AnalysisLenses`, `AnalysisObjectives`, `LensCoverage`

The page renders whatever the endpoint returns and hardcodes no lens vocabulary, which
`tests/test_analysis_registry_gui_parity.py` enforces. That test also compares the backend
`LOADERS` map against the frontend `ENTITIES` map — they are hand-maintained mirrors, and
`Promise.allSettled` in `SkywatcherData.jsx` swallows a 404, so a name on one side but not
the other would render as a silently empty table.

## Verify

```bash
pytest -q tests/test_analysis_lens_registry.py \
          tests/test_analysis_registry_gui_parity.py \
          tests/test_satim_artifact_crosswalk.py \
          tests/test_satim_lens_wiring.py

# The gate fails closed on a missing or self-inconsistent registry
python -m skywatcher.core.ontology_gate --config-dir configs

# End to end, emitting a coverage report
python -m fr24_image_skill run <input> --output-dir /tmp/run --mode forensic
cat /tmp/run/coverage_report.json
```
