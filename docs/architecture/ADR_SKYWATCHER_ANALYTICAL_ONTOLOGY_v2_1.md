# SKYWATCHER ANALYTICAL ONTOLOGY v2.1 — UNFREEZE AND AMENDMENT

**Status:** ACTIVE
**Supersedes:** `ADR_SKYWATCHER_ANALYTICAL_ONTOLOGY_v2_0.md` §15 (implementation lock) and the specific clauses named below. Everything v2.0 says that is not amended here remains binding.
**Baseline:** `jotaele44/skywatcher-pr@f940dc1d4afae7740eaa2a94dbf4684d11ae156b`
**Unfreeze date:** 2026-08-08
**Authority:** Human-authorized ontology unfreeze vector
**Frozen baseline:** `docs/architecture/archive/v2_0/` (byte-identical to the v2.0 freeze; hashes recorded in `SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json` under `frozen_baseline_records`)

---

## 0. Why this exists

v2.0 was frozen as a governance-only baseline: it described the ontology the
repository *should* have, and then forbade the repository from changing to match it.
§15 stated that no branch, commit, schema change, code change, documentation change,
workflow rename, data migration, or runtime behavior change was authorized until a
separate implementation vector approved an exact change set.

This document is that vector. It lifts the lock and records four decisions.

The freeze is not being erased. The seven v2.0 artifacts are archived verbatim under
`docs/architecture/archive/v2_0/` and their SHA-256 values remain recorded and
test-enforced, so the pre-unfreeze state stays provable and a re-freeze remains
possible at any time.

---

## A0 — Unfreeze

The v2.0 §15 implementation lock is lifted. The governance registries become living
documents:

- `SKYWATCHER_TERM_OWNERSHIP_MATRIX_v2_0.csv`
- `SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv`
- `SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv`
- `SKYWATCHER_LEGACY_ALIAS_REGISTRY_v2_0.csv`
- `SKYWATCHER_ONTOLOGY_SOURCE_REGISTER_v2_0.csv`

They keep their v2.0 filenames. Renaming immutable historical artifacts in place is
prohibited by v2.0 §13.8, and the archive — not the filename — is what carries the
historical record.

`SKYWATCHER_ONTOLOGY_FREEZE_MANIFEST_v2_0.json` moves to
`status: UNFROZEN_IMPLEMENTATION_AUTHORIZED` and lifts
`schema_change_authorized`, `runtime_change_authorized`,
`threshold_execution_authorized`, and `workflow_change_authorized`.
`force_push_authorized` and `auto_merge_authorized` stay `false`: they govern git
operations, not ontology, and nothing here needs them.

### A0.1 What replaces the freeze

`tests/test_skywatcher_ontology_governance_v2.py` previously encoded the freeze as
exact row counts (27 terms / 24 aliases / 20 thresholds / 77 migration rows split
8 authorized and 69 blocked), `is False` assertions on every authorization boolean,
and a SHA-256 recompute over all seven artifacts.

It is rewritten as **structural invariants that hold at any size**: header
conformance, key uniqueness, complete ADR §12 threshold records, recognized approval
states, prohibited thresholds staying non-executable, and a hash recompute against
the archived baseline.

Adding a term or a threshold is now normal work. Regressing the *shape* of a
registry, or quietly losing the frozen baseline, still fails the build. Unfreezing
the ontology is not the same as leaving it unchecked.

---

## A1 — Bounded facility-function classification

**Amends v2.0 §7** ("SATIM never infers facility purpose…") and the
`purpose_inference` invariant.

SATIM may emit `DUAL_USE_FUNCTION_CANDIDATE`: a claim that a structure's *observable
form* is compatible with more than one plausible function.

This is permitted only as a **Finding** in the v2.0 §4 sense — a single-domain
interpretation supported by observations and measurements — and only with the full
§5.3 confidence record attached:

| Required field | Meaning |
|---|---|
| `confidence_score` | method-bounded epistemic confidence |
| `confidence_method` | named method that produced it |
| `confidence_scope` | what the number is *about* |
| `method_version` | version of that method |
| `supporting_observation_ids` | the observations it rests on |
| `limitations` | what would overturn it |

plus a mandatory `interpretation_restriction`.

### A1.1 What this does not authorize

The distinction this amendment turns on: **facility function/affordance** is now in
scope; **mission and intent** are not.

Still prohibited, unchanged from v2.0:

- mission or intent inference of any kind — `mission_or_intent_inference_authorized`
  remains `false` in the manifest;
- ownership, access, coordination, or wrongdoing claims;
- operational recommendation, live cueing, or physical field direction;
- deriving function from operator identity, callsign, route shape, altitude, speed,
  duration, or POI proximity;
- promoting `candidate` to `confirmed` without a named review gate.

The aircraft-type-to-mission fallback in
`skywatcher.legacy.quarantined_mission_inference` stays quarantined. This amendment
does not reopen it, and `src/skywatcher/fpim/aircraft_profile.py` is deliberately
excluded from A3.

### A1.2 Compatibility

`purpose_inference` is retained in `satim_finding.schema.json` with
`{"const": false}`. It now means specifically *unbounded* purpose inference, which
remains prohibited. The bounded channel is a new, optional `function_assessment`
object. Existing findings and existing consumers are unaffected; this is additive
per v2.0 §13.2.

---

## A2 — Threshold execution

**Amends v2.0 §12** and lifts `threshold_execution_authorized`.

A threshold may execute once it carries a complete §12 record: `threshold_id`,
`owner`, value and unit, purpose, `status`, validation artifact,
`effective_version`, supersession lineage, and failure behavior. Two columns
(`effective_version`, `supersedes`) are added to the threshold registry to complete
that record, and two statuses (`EXECUTABLE_CANDIDATE`, `VALIDATED`) are added to the
allowed set.

Two binding conditions:

1. **Every executed threshold stamps its provenance into output** as
   `{threshold_id, value, status}`. A consumer must always be able to see that a
   number came from a `CANDIDATE`-grade cutoff rather than a validated one.
2. **`PROHIBITED` stays prohibited.** `ILAP-IDENTITY-PRIORITY` — weak aircraft
   identity increasing review priority — is not executable and does not become so.

`EXECUTABLE_CANDIDATE` means "wired up and running, empirically unvalidated". It is
not a claim of correctness, and it does not satisfy §5.3 on its own.

---

## A3 — Path authorizations

The following `SKYWATCHER_PATH_LEVEL_MIGRATION_PLAN_v2_0.csv` rows move off
`BLOCKED_SEPARATE_APPROVAL_REQUIRED`:

| Path | New state | Scope |
|---|---|---|
| `schemas/satim_artifact_assessment_v1.schema.json` | `AUTHORIZED` | Full row: v1 stays immutable, v2 is created with threshold/method metadata |
| `src/skywatcher/corrim/ilap_airspace_bridge.py` | `AUTHORIZED_THRESHOLD_BINDING` | **Threshold binding only.** The same row's field renames, identity-priority removal, and mission-label scoping remain blocked |

`AUTHORIZED_THRESHOLD_BINDING` exists so a row whose planned action bundles several
changes can have one of them authorized without implying the rest.

Every other blocked row stays blocked. In particular
`src/skywatcher/fpim/aircraft_profile.py`, `src/skywatcher/core/module_boundaries.py`,
and the P0-INTEGRATED workflow and package rows are untouched by this vector.

---

## Conformance

v2.0 §14's conformance gates remain in force, with one substitution: "thresholds
carry status metadata" is now also enforced at execution time by the stamping
requirement in A2.

Adding to this ontology means editing the registries and letting
`tests/test_skywatcher_ontology_governance_v2.py` check the shape. Removing the
archive under `docs/architecture/archive/v2_0/`, or weakening the invariant test to
make a change pass, is out of scope for any implementation vector and requires a new
governance decision.
