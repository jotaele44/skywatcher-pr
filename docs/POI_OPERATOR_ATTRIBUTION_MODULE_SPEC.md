# POI Operator Attribution Module — Specification v1.1.0

**Repository:** `skywatcher-pr`
**Family:** `poi` (new workflow family; siblings: `skywatcher`, `satim`, `terrain`, `shared`)
**Status:** implementation-ready spec
**Provenance tier:** `SPEC_AUTHORED` — see §9

---

## 0. Problem statement

Given a footprint with **no map label**, determine which organizations operate at that site,
without a human in the loop, at a confidence level that survives publication.

Worked example: the circled structure north of Hipódromo Camarero, between PR-3 and PR-66,
Canóvanas. Two joined buildings, large truck court, no label on the basemap.

## 1. The confidence claim is reframed

No imagery-derived inference reaches 99% on **identity**. What reaches high confidence is
**documentary convergence on a parcel key**.

The module therefore runs two engines that never read each other's outputs:

| | Engine A — geometric | Engine B — documentary |
|---|---|---|
| Skill | `poi-facility-class-profiler` | `poi-operator-attribution` |
| Input | raster + footprint polygon | catastro parcel key |
| Emits | facility **class** + prior | **named** roles + source lineage |
| May emit a name | **never** | always |
| May promote state | **never** | proposes only; gate decides |

Attribution is Engine B, corroborated but never caused by Engine A. If A fires alone, the record
stays `UNRESOLVED`. This preserves the existing GPW rule: a name is a positive finding or it does
not exist. Amount-matching, footprint-matching, and class-matching are all formally rejected as
attribution methods.

**Published confidence = blind holdout precision of the full pipeline (§8). Nothing else.**

## 2. Pipeline

```text
raster tile + drawn/derived footprint
        │
        ├──► [A] poi-facility-class-profiler ──► facility_class + prior   (name-free)
        │
        └──► poi-parcel-resolver ──► catastro key ──► [B] poi-operator-attribution
                                                              │
                                                              ▼
                                              poi-attribution-promotion-gate
                                                              │
                                                              ▼
                                                   poi_record (state-stamped)
```

Orchestration: `poi-attribution-operator`. Scope enforcement: existing `task-scope-guard`.
Export: existing `airspace-export-validator` (extend `poi` schema family).

## 2A. Target Geometry Binding Invariant

A discovered POI name is **not** the identity of the selected footprint merely because it is nearby, prominent, category-compatible, or ranked first by a map/business search. The pipeline MUST freeze the target geometry before discovery and maintain the full candidate set separately.

Forbidden identity proofs include `NEAREST_ONLY`, `PROXIMITY_ONLY`, search-result rank, same category, and an unbound nearby basemap label. These are discovery signals only. A named candidate requires affirmative binding to the target by resolved parcel join, point-in-polygon, authoritative coordinate/address tied to that parcel, or an equivalently documented spatial relationship.

**Negative regression case — Canóvanas:** a Walmart Supercenter is a legitimate nearby POI northeast of the Econo warehouse complex. A nearby-business lookup can therefore return Walmart while the selected footprint is actually `Centro de Distribución Econo`. Wider-context imagery demonstrates that the two occupy distinct properties. The correct behavior is to reject/supersede the Walmart candidate, retain it as a search false-positive fixture, and label the target only from evidence bound to the target geometry.

This invariant applies before operator-role promotion and is independent of Engine A facility morphology. A plausible facility class cannot repair a failed geometry binding.

## 3. Parcel resolution — the hard part

PR street addressing (`PR-3 Km 15.2, Bo. Hato Puerco`) is not resolvable by conventional
geocoders. This is where most attribution errors are born, so it is its own skill.

### 3.1 Address grammar (normalized)

```text
route_class : PR | Carr. | Ave. | Calle | Camino Municipal
route_id    : integer, optional ramal suffix  (PR-181 R-1)
km          : decimal
hm          : integer 0–9, hectómetro; km_true = km + hm/10
qualifier   : Int. (interior) | Bo. <barrio> | Sector <name> | Parque Industrial <name>
municipio   : required for disambiguation of barrio and sector names
```

`Hm` is silently dropped by most parsers. Dropping it introduces up to a 900 m error — enough to
land on the wrong parcel in this corridor. It is a hard-required field when present.

### 3.2 Resolution steps

1. Parse to the grammar above; refuse ambiguous parses (fail closed).
2. Look up DTOP route centerline geometry for `route_id` (+ ramal).
3. Linear-reference `km_true` along the centerline from the route's **published origin**,
   honouring any documented km-origin reset for that route segment.
4. Buffer the resulting point; intersect against CRIM catastro parcel polygons.
5. Tie-break by side-of-road when the qualifier supplies it; otherwise return all candidates
   as `AMBIGUOUS` — never pick the nearest.
6. Emit `catastro` + `resolution_method` + `residual_uncertainty_m`.

Reference implementation: `km_marker_resolver.py` (stub, deterministic, fail-closed).

## 4. Role model — four fields, never one

A single `operator` field is the module's most dangerous possible design. Emit four:

| Field | Meaning | Typical source |
|---|---|---|
| `PARCEL_OWNER` | holds title to the catastro | CRIM, Registro de la Propiedad |
| `PERMIT_HOLDER` | named on the permiso de uso | OGPe / SBP |
| `OPERATOR` | runs the facility day to day | EPA FRS/RCRA, FDA, DRNA, EQB |
| `TENANT[]` | occupies bays/suites under the operator | DDEC registry, WARN, postings |

**Multi-tenant is the default hypothesis.** Single-tenant must be affirmatively demonstrated
(single permiso de uso covering full footprint, or single RCRA handler at the parcel with no
sub-suite addressing). For a footprint this size — holding company owns, 3PL operates, three
clients occupy — is the *normal* case, not the exception.

Each role carries: `name`, `normalized_name`, `entity_id`, `source_tier`, `source_ref`,
`effective_from`, `effective_to`, `observed_at`, `method`.

## 5. Source tiers

**Tier 1 — operator names itself to a regulator, with coordinates.**
EPA FRS / ECHO (RCRA handler ID, NPDES, TRI), FDA establishment registration, OGPe permisos
de uso y construcción, DRNA water-withdrawal and discharge franchises, EQB air permits, OSHA
inspection records.

**Tier 2 — operator names itself with an address.**
Departamento de Estado / DDEC corporate registry, SAM.gov registrant, USAspending recipient,
customs importer of record, WARN notices, Depto del Trabajo filings, job postings bearing a
street address.

**Tier 3 — circumstantial; corroborates only, never establishes.**
Fleet livery, signage in street-level imagery, geotagged photos, freight-broker listings,
employee-declared work locations.

### 5.1 Independence test

Two sources are independent iff **different issuing authority** AND **neither derives from the
other**. ECHO derives from RCRA — not independent. A corporate-registry address copied from a
permit — not independent. Two Tier-2 records sharing a filing agent — not independent.

Failure of the independence test is the most common cause of false `CONFIRMED`. Test it
explicitly; log the result.

## 6. Promotion state machine

States: `UNRESOLVED` · `CANDIDATE` · `PROBABLE` · `CONFIRMED` · `CONTESTED` · `LAPSED`

| From | To | Condition |
|---|---|---|
| UNRESOLVED | CANDIDATE | catastro resolved AND ≥1 Tier-2 or Tier-3 source joins to it |
| CANDIDATE | PROBABLE | ≥1 Tier-1 **or** ≥2 independent Tier-2, same catastro, temporal window satisfied |
| PROBABLE | CONFIRMED | ≥2 independent sources incl. ≥1 Tier-1 · temporal consistency PASS · contradiction register empty · role fields disambiguated · tenancy cardinality adjudicated |
| any | CONTESTED | conflicting names in the same role with overlapping validity intervals |
| CONFIRMED | LAPSED | newest corroborating source older than TTL (default 540 d) or permit expired |
| any | UNRESOLVED | parcel key retracted or invalidated |

**Invariants**

- Engine A output may not appear in any transition condition. Hard rule, enforced at gate input.
- Absence of a map label is **not evidence**. It may not appear in any condition either.
- Promotion requires evidence; **demotion never does**. The asymmetry is deliberate.
- `CONTESTED` never auto-resolves. Both records persist; nothing is averaged away.
- Temporal consistency compares **imagery capture date** against permit effective intervals.
  This is the same class of failure as the orthomosaic seam false positive — a stale tile
  attributed to a current operator is the identical error wearing different clothes.

## 7. Record schema

Canonical: `poi_attribution_record.schema.json`. Keyed on catastro; geohash fallback only while
`UNRESOLVED`. Carries `contradiction_register[]`, `temporal_consistency{}`, and a
`hydro_infra{}` block (§10).

## 8. Validation harness — where the number comes from

1. Assemble ≥50 PR parcels whose operators are already established (labeled DCs, the
   Barceloneta–Manatí pharma belt, Caguas/Toa Baja food distribution, Guaynabo/Carolina 3PL).
2. Withhold all labels and all operator strings from the pipeline.
3. Run end to end. Score `CONFIRMED` records only.
4. **Blind precision on that holdout is the module's confidence figure.** Assert nothing higher.
5. Report recall separately. A module that confirms 6 of 50 at 100% precision is working
   correctly and must not be tuned toward coverage.
6. Re-run on every schema, tier-table, or gate change. Precision regression blocks release.

Engine A is scored separately on class accuracy and never contributes to the attribution number.

## 9. Provenance note

Existing packages use tiers `VERBATIM`, `SPEC_RECOVERED`, `SPEC_RECONSTRUCTED`. These five
packages are newly authored — not recovered from a prior session — and are stamped
`SPEC_AUTHORED`. Register that value in the family policy before merge rather than mislabeling
them as recovered.

## 10. Hydro / infrastructure enrichment

Standing fields, because they are frequently the **fastest path to a named operator** and they
tie POI work into the existing dam-corridor evidence base:

- `basin` and upstream impoundment. The example parcel sits in the lower Río Grande de Loíza
  basin, **downstream of Carraízo** — any DRNA withdrawal franchise or NPDES outfall here is a
  named-operator document already inside your contracting investigation's blast radius.
- PRASA industrial service connection; PREPA feeder and transformer-yard capacity.
- Karst/carbonate flag and mapped subsurface void proximity — the Canóvanas–Loíza lowland sits
  off the northern carbonate platform edge, so this parcel should flag `karst_adjacent: false`
  while corridor sites west of it flag true. Keep the field regardless; a null is a finding.

## 11. Skill packages

| Package | Family | Responsibility |
|---|---|---|
| `poi-parcel-resolver` | poi | address/km-marker → catastro, fail-closed |
| `poi-facility-class-profiler` | poi | name-free geometric class prior |
| `poi-operator-attribution` | poi | documentary join → named roles |
| `poi-attribution-promotion-gate` | poi | sole authority over state transitions |
| `poi-attribution-operator` | poi | bounded end-to-end orchestration |

## 12. Open items

- DTOP centerline source of record and its km-origin reset history — unresolved.
- CRIM parcel polygon access path (bulk vs per-query) — unresolved.
- TTL of 540 d is a placeholder; derive it from observed permit-renewal intervals.
- Suite-level addressing inside multi-tenant footprints has no clean PR-side key.
