# SKYWATCHER ANALYTICAL ONTOLOGY v2.0 — FROZEN MANUAL SPECIFICATION

**Status:** FROZEN_PENDING_IMPLEMENTATION_AUTHORIZATION  
**Repository baseline:** `jotaele44/skywatcher-pr@140b954b6faa9a50e26ad38fd56b0bc038ea6c25`  
**Freeze date:** 2026-08-03  
**Authority:** Human-authorized ontology adjudication; no repository write authority  
**Supersedes:** The manual v2.0 draft wherever this document differs

---

## 1. Normative decision

Skywatcher adopts a **seven-component conceptual model** with **four active analytical/contract domains**, one extraction pipeline, one umbrella system, and one quarantine surface:

1. **Skywatcher** — umbrella airspace-analysis producer and repository.
2. **Core** — domain-neutral contracts, provenance, geometry/time, evidence axes, registries, normalization, receipts, and validation.
3. **RLSM** — extraction and observation-localization pipeline.
4. **SATIM** — imagery and terrain interpretation domain.
5. **FPIM** — flight-path interpretation domain.
6. **CORRIM** — cross-domain reconciliation and review-integration domain.
7. **Legacy** — compatibility and quarantined historical behavior.

The current import-enforced repository buckets remain `core`, `satim`, `fpim`, `corrim`, and `legacy`. RLSM is not promoted to a peer analytical domain; implementation may add an explicit pipeline-owner classification overlay without changing that analytical hierarchy.

---

## 2. Canonical names and types

| Identifier | Canonical long name | Type | Canonical owner |
|---|---|---|---|
| Skywatcher | Skywatcher | Umbrella system | Repository/program |
| Core | Skywatcher Core | Shared contract layer | Core |
| RLSM | Restricted/Lossless Screenshot Mining | Extraction and localization pipeline | RLSM pipeline under Core governance |
| SATIM | Satellite/Screenshot and Terrain Imagery Module | Single-domain analytical module | SATIM |
| FPIM | Flight-Path Interpretation Module | Single-domain analytical module | FPIM |
| CORRIM | Cross-domain Observation Reconciliation and Review Integration Module | Cross-domain analytical module | CORRIM |
| Legacy | Skywatcher Legacy Quarantine | Compatibility/quarantine surface | Legacy |
| ILAP | Infrastructure-Linked Airspace Point | Review-only cross-domain association object | CORRIM |
| AASB | Airspace-Asset Spatial Bridge | Export/adapter surface | CORRIM adapter |
| PRII | Puerto Rico Integrated Intelligence | Federation name | Federation authority |

### 2.1 Historical aliases

Historical expansions remain searchable aliases only. They must not appear as new schema definitions, module descriptions, or user-facing canonical names.

- RLSM: `route-line-segment mining` → deprecated collision.
- SATIM: `satellite/screenshot imagery` → retained historical gloss.
- ILAP: `Infrastructure-Linked Airspace Profile`, `Infrastructure-Linked Access Point`, `inferred landing access point` → historical aliases.
- AASB: `Aerial Anomaly Surveillance Band` → deprecated; use `AIRSPACE_CORRIDOR_BAND` for a neutral band concept.
- PRIIS → deprecated variant unless federation-wide authority establishes a distinct meaning.

---

## 3. Domain boundaries

| Owner | Permitted responsibilities | Prohibited responsibilities |
|---|---|---|
| Core | Shared schemas, provenance, evidence axes, source identity, geometry/time/uncertainty, registries, normalization, receipts, validation, readiness aggregation | Imagery classification, trajectory interpretation, cross-domain significance, intent inference |
| RLSM | Inventory, hashing, availability, segmentation, OCR, visible label/icon/aircraft extraction, pixel geometry, source-frame localization, immutable extraction receipts | Terrain interpretation, behavioral interpretation, mission inference, infrastructure significance, predictive routing |
| SATIM | Image provenance, registration, artifact classification, imagery contamination assessment, terrain/landcover observations, multi-epoch and cross-source image testing | Flight behavior, mission/purpose, SATIM–FPIM fusion |
| FPIM | Aircraft identity as observed/registry-resolved, track reconstruction, endpoint candidates, trajectory measurements, label-independent behavior characterization, neutral POI proximity enumeration | Imagery interpretation, mission/purpose inference, POI significance against imagery |
| CORRIM | Join SATIM and FPIM outputs, spatial/temporal association, null testing, contradiction reconciliation, review-context reporting | Primary extraction, causal claims, intent inference, live cueing, physical field direction |
| Legacy | Preserve exact old interfaces and historical records | Supply new active findings, bypass current gates, become an active dependency |

### 3.1 Import and consumption rule

```text
Core      → Core only
            Exception: readiness_engine may consume a SATIM status artifact solely for readiness aggregation.
RLSM      → Core + RLSM pipeline components
SATIM     → Core + versioned RLSM observation contracts + SATIM
FPIM      → Core + versioned RLSM observation contracts + FPIM
CORRIM    → Core + versioned SATIM outputs + versioned FPIM outputs + CORRIM
Legacy    → quarantined; active owners may not import Legacy
```

The existing Core-to-SATIM readiness exception remains explicit, narrow, tested, and non-analytical. It does not authorize Core to combine evidentiary findings.

### 3.2 RLSM localization boundary

RLSM may calculate pixel-to-map transforms, affine-fit evidence, uncertainty, and geometry status **only to localize extracted observations**. It may not classify terrain, interpret a ground feature, or assign significance. Any ground-feature blob pass using semantic classes such as `pad`, `tank`, or `quarry` belongs to SATIM or Legacy and must not be treated as default RLSM extraction.

---

## 4. Canonical analytical objects

| Object | Definition | Owner |
|---|---|---|
| Source artifact | Preserved original input or authoritative external record | Core |
| Extracted observable | Source-visible or mechanically extracted datum with provenance | RLSM/Core |
| Observation | Source-grounded statement of what is present, absent, visible, or recorded | Core/domain |
| Measurement | Quantified result under a named method and version | Core/domain |
| Finding | Single-domain interpretation supported by observations and measurements | SATIM or FPIM |
| Association | Tested cross-domain relationship, explicitly non-causal | CORRIM |
| Hypothesis | Falsifiable explanatory proposition kept separate from findings | Analyst/CORRIM review layer |
| Assessment | Human-reviewed judgment weighing support, contradictions, and alternatives | Analyst |
| Claim | Publishable assertion with scope, citations, confidence, and caveats | Publishing authority |
| Operational recommendation | Direction to act in a live or physical environment | Out of scope for Skywatcher analytics |

Forbidden promotions:

- extraction score → confidence;
- recurrence → corroboration;
- proximity → significance;
- source tier → truth;
- review priority → evidence strength;
- operator/callsign identity → mission;
- cross-domain association → causation;
- `candidate` → `confirmed` without a named review gate.

---

## 5. Independent evidence axes

These fields are orthogonal and must not be collapsed:

1. `evidence_tier` — source class/verifiability.
2. `visibility_class` — relationship to the source artifact.
3. `provenance_status` — source/lineage completeness.
4. `source_availability` — present, missing, restored, archived, or unknown.
5. `geometry_status` — located, approximate, unlocated, invalid.
6. `temporal_status` — exact, approximate, missing, invalid.
7. `review_status` — unreviewed, needs review, accepted, rejected, superseded.
8. `hypothesis_status` — not proposed, proposed, supported, contradicted, unresolved.
9. `confidence_score` — method-bounded epistemic confidence.
10. `review_priority` — queue ordering only.

### 5.1 Evidence tiers

| Tier | Canonical meaning |
|---|---|
| T1 | Technical, sensor-derived, official, or independently machine-verifiable evidence |
| T2 | Operational or official structured record with auditable provenance |
| T3 | Eyewitness, field observation, or analyst annotation |
| T4 | Secondary context or lead-generation material |

A screenshot is not automatically T2 merely because it depicts a tracking application; tier assignment depends on provenance, integrity, and the specific claim.

### 5.2 Visibility classes

| Class | Meaning |
|---|---|
| V0 | Directly visible or recorded in the source |
| V1 | Mechanically derived under a declared method from V0 material |
| V2 | Context supplied to the run but not visible in the source |
| V3 | External-registry-only information |
| V4 | Analyst hypothesis only |

### 5.3 Confidence governance

Every confidence value requires:

- `confidence_score`;
- `confidence_method`;
- `confidence_scope`;
- `method_version`;
- supporting observation IDs;
- contradiction/limitation fields where applicable.

The existing SATIM levels `CONFIRMED`, `HIGH`, `MODERATE`, `LOW`, and `UNRESOLVED` remain compatibility values only until validated. For artifact identity, new terminology must use `CONFIRMED_ARTIFACT`; all current numeric boundaries are `CANDIDATE`, not normative universal thresholds.

---

## 6. RLSM specification

**Canonical expansion:** Restricted/Lossless Screenshot Mining.  
**Type:** Extraction and observation-localization pipeline.

Permitted outputs include source manifests, SHA-256/phash values, OCR records, word boxes, visible aircraft labels, visible place labels, icon observations, pixel coordinates, source-frame transforms, localization uncertainty, availability states, extraction receipts, and review queues.

RLSM must not produce route significance, behavioral labels beyond mechanical geometry primitives, mission/purpose labels, infrastructure associations, predictive routes, graph significance, or terrain/ground-feature findings.

Files and commands may retain `rlsm` identifiers. New descriptions must use the canonical expansion.

---

## 7. SATIM specification

**Canonical expansion:** Satellite/Screenshot and Terrain Imagery Module.  
**Type:** Imagery/terrain analytical domain.

SATIM owns:

- image-source and acquisition-epoch assessment;
- image registration and calibration used for imagery interpretation;
- tile, mosaic, compression, blur, atmospheric, parallax, orthorectification, and temporal-composite artifact classes;
- visual contamination controls;
- imagery-derived feature candidates;
- cross-source and multi-scale image tests;
- interpretation restrictions.

Canonical label changes:

- `TRACK_LINE` → `SOURCE_OVERLAY_TRACK_LINE` when referring to application-rendered route geometry.
- `STRUCTURAL_SIGNAL` → `STRUCTURAL_FEATURE_CANDIDATE`.
- bare `SHADOW` is prohibited; use `IMAGE_SHADOW`, `SHADOW_CONFUSION`, `TRACK_GAP`, or `DATA_BLACKOUT`.
- bare `CONFIRMED` → `CONFIRMED_ARTIFACT` only when artifact identity is the scope.

SATIM never infers facility purpose, aircraft behavior, mission, intent, wrongdoing, or cross-domain significance.

---

## 8. FPIM specification

**Canonical expansion:** Flight-Path Interpretation Module.  
**Type:** Flight-path and trajectory analytical domain.

FPIM owns track reconstruction, multi-frame flight fusion, endpoint candidates, trajectory geometry, recurrence measurement, behavior characterization, and neutral exhaustive POI proximity enumeration.

Canonical behavior terms:

| Legacy | Canonical |
|---|---|
| TAKEOFF | TAKEOFF_CANDIDATE unless independently verified |
| LANDING | LANDING_CANDIDATE unless independently verified |
| INSPECTION | CORRIDOR_FOLLOWING |
| COORDINATION | Cross-aircraft association; move to CORRIM |
| SHADOW | TRACK_GAP or DATA_BLACKOUT |
| PATTERN_BREAK | ROUTE_DEVIATION or BASELINE_DEVIATION |

### 8.1 Mission and purpose

FPIM may preserve a mission/purpose label only when it is explicitly sourced from an authoritative record or explicitly stored as a V4 analyst hypothesis. It must never derive mission from aircraft type, callsign, route shape, speed, altitude, duration, operator identity, or POI proximity.

The current active aircraft-type-to-mission fallback is a **blocking P0 nonconformance**. The ontology freezes its destination as Legacy or an explicitly disabled compatibility gate; it is not accepted as active FPIM behavior.

### 8.2 POI rule

FPIM proximity outputs are neutral geometry measurements. Use fields such as `proximity_match_method`, `distance_m`, and `proximity_match_score`. They must not imply relevance, intent, access, or facility relationship.

---

## 9. CORRIM specification

**Canonical expansion:** Cross-domain Observation Reconciliation and Review Integration Module.  
**Type:** Cross-domain association and review-integration domain.

CORRIM is the sole owner of SATIM–FPIM association. Outputs must identify contributing finding IDs, spatial/temporal methods, null/alternative tests, contradictions, data gaps, score semantics, method version, and a review-only operator posture.

`correlation_score` is not a probability of causation. New schemas should use `association_score` with an explicit scoring method and interpretation. `operator_action=review_context_only`, `live_tracking=false`, and `operational_cueing=false` remain binding.

### 9.1 ILAP

**ILAP — Infrastructure-Linked Airspace Point** is a review-only point or bounded area where flight-path evidence and infrastructure reference context meet under a declared spatial method. It does not assert access, landing, facility purpose, ownership, coordination, causation, or operational relevance.

Current ILAP weights, grid sizes, distance bands, fallback scores, and priority bands are `CANDIDATE`. Weak aircraft identity must not increase review priority.

### 9.2 AASB

**AASB — Airspace-Asset Spatial Bridge** is an adapter/export surface. It is not a domain and not a confidence model. A value derived from `flight_count / 5` must be named as an edge-support or recurrence metric, not `confidence_score`.

---

## 10. Visual and integrated engine adjudication

The legacy L1–L5 stack is renamed the **Skywatcher Visual Calibration Stack**. Layer identifiers remain compatibility labels:

| Layer | Current function | v2.0 owner |
|---|---|---|
| L1 | UI segmentation | RLSM |
| L2 | Route extraction | FPIM calibration using RLSM visual primitives |
| L3 | Vision/OCR | Split between RLSM OCR and SATIM imagery classification |
| L4 | Aircraft intelligence | FPIM identity enrichment; mission inference prohibited |
| L5 | Tile seam/shadow | SATIM artifact calibration |

### 10.1 Runner and package dispositions

| Existing surface | Frozen disposition |
|---|---|
| `python -m fr24.satim_engine` | Legacy command for the **Repo-native Visual Calibration Orchestrator**; multi-owner orchestrator, not SATIM domain code by name alone |
| `tools/satim_engine` and `satim` CLI | **Legacy Integrated Track/Visual Analysis Engine** pending decomposition; cannot be represented as imagery-only SATIM because it parses tracks and emits graph/track ledgers |
| `tools/satim_route_findings` | **Legacy FPIM Route Findings Utility** pending ledger-name and graph-owner disentanglement |
| `.github/workflows/satim-engine-ci.yml` | Legacy workflow name; migration must follow package disposition without breaking release history |

“SATIM engine” without an implementation qualifier is prohibited in new documentation.

---

## 11. Legacy and project-language adjudication

| Term | Frozen decision |
|---|---|
| FN | `FLIGHT_EVENT_RECORD`; old flight-node/number/narrative meanings are aliases |
| UF | `UNRESOLVED_FLIGHT_EVENT` |
| FLOWER / PETAL / THREAD / WEB | Historical UI/search aliases only |
| ECHO | `PATTERN_RECURRENCE` |
| SHADOW | Prohibit bare term; qualify by domain |
| P_ROUTE | Reserved experimental forecasting term; outside active ontology |
| HTF | Reserved experimental forecast-horizon term |
| FNEPB | Reserved experimental ensemble term |
| ARCI | Deprecated; use `ROUTE_RECURRENCE_INDEX` with explicit formula/denominator |
| CHBL | Deprecated; use `CROSS_AIRCRAFT_SPATIOTEMPORAL_ASSOCIATION` in CORRIM |
| SPM | Deprecated; split into `IMAGE_SHADOW_MASK` or `TRACK_GAP_LIKELIHOOD_SURFACE` |
| BOGR | Prohibited in active analytics; any field review planning is a separate human workflow |
| AIRSPACE_CORRIDOR_BAND | Replacement for legacy AASB band meaning |

---

## 12. Threshold governance

Every threshold requires:

- `threshold_id`;
- `owner`;
- `value` and unit;
- purpose and scope;
- `status` = `CANONICAL`, `VALIDATED`, `CANDIDATE`, or `CALIBRATION_REQUIRED`;
- validation artifact;
- effective version;
- supersession lineage;
- failure behavior.

Until independently validated, current SATIM promotion cutoffs, artifact-confidence cutoffs, ILAP distance bands and weights, AASB five-flight saturation, grid-cell sizes, and identity-related priority rules are `CANDIDATE` or `PROHIBITED` as recorded in the threshold registry.

---

## 13. Compatibility policy

1. Preserve historical raw fields and values.
2. Add canonical fields before retiring legacy fields.
3. Emit explicit alias metadata during transition.
4. Do not silently reinterpret existing records.
5. Keep legacy commands as wrappers where needed.
6. Version any schema with semantic field changes.
7. Require old/new parity fixtures and deterministic migration receipts.
8. Do not rename immutable historical artifacts in place.

---

## 14. Conformance gates

An implementation is conformant only when:

- every active file has one canonical owner;
- RLSM is not used as a route/behavior/network analytical umbrella;
- SATIM code and docs contain no flight-behavior ownership;
- FPIM contains no active mission/purpose inference;
- CORRIM alone combines SATIM and FPIM outputs;
- all generic scores state scope and method;
- evidence axes remain separate;
- legacy aliases are accepted only through explicit compatibility paths;
- thresholds carry status metadata;
- tests cover prohibited cross-domain imports and prohibited intent inference;
- no production, live cueing, or physical-action authority is introduced.

---

## 15. Freeze authority and implementation lock

The twelve substantive ontology decisions are frozen with the revisions recorded in `SKYWATCHER_BALLOT_ADJUDICATION_v2_0.md`. Repository modifications are **not authorized** by this freeze. No branch, commit, pull request, schema change, code change, documentation change, workflow rename, data migration, or runtime behavior change may be performed until a separate implementation vector approves an exact change set.
