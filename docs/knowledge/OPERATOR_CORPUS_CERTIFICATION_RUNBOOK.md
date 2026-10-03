# Operator corpus certification runbook — implication sidecar v0.1

**Status:** operator-local execution package; migration 0004 remains unregistered and normal-startup activation remains disabled.

This runbook closes only the remaining machine-local evidence gates for PR #332. It reads the RLSM and Master Flight Log databases in read-only mode, runs the existing RLSM v2 audit against the independently reviewed 300-frame gold file, generates a bounded screenshot↔MFL candidate denominator, requires explicit operator adjudication, and materializes the reviewed result into a **separate scratch sidecar database**.

It does **not** modify the RLSM database, the MFL database, canonical flight rows, or the migration ledger.

## 1. Freeze the checkout

From the operator machine:

```bash
cd ~/Documents/GitHub/skywatcher-pr
git switch feat/knowledge-implication-sidecar-v0-1
git pull --ff-only
GIT_SHA="$(git rev-parse HEAD)"
printf '%s\n' "$GIT_SHA"
```

Do not continue if the branch is dirty in a way that changes source, schema, test, RLSM, or MFL semantics.

## 2. Required local inputs

Default paths:

```text
data/rlsm/rlsm_screenshot_analysis.sqlite
data/skywatcher.db
data/FR24_baseline/
data/rlsm/gold_sample_300.jsonl
```

The gold file must contain exactly 300 uniquely resolved screenshots. Every row must include an explicit `labels` field, including `[]` for reviewed absence, plus non-empty `annotator` and `reviewed_by` values that identify different reviewers.

Source imagery and local databases remain operator-local and must not be committed merely to satisfy this procedure.

## 3. Preflight — read only

```bash
python3 scripts/knowledge_operator_certification.py preflight \
  --expected-git-sha "$GIT_SHA" \
  --rlsm-db data/rlsm/rlsm_screenshot_analysis.sqlite \
  --mfl-db data/skywatcher.db \
  --corpus-root data/FR24_baseline \
  --gold data/rlsm/gold_sample_300.jsonl
```

Required result:

```text
status = PASS
gold_review.status = PASS
migration_0004_registered = false
canonical_mfl_mutation_authorized = false
```

A missing database, ambiguous gold identity, duplicate resolved frame, non-independent gold review, missing explicit labels, Git-SHA drift, or missing required tables fails closed.

## 4. Generate the bounded binding denominator

```bash
python3 scripts/knowledge_operator_certification.py generate-bindings \
  --expected-git-sha "$GIT_SHA" \
  --rlsm-db data/rlsm/rlsm_screenshot_analysis.sqlite \
  --mfl-db data/skywatcher.db \
  --corpus-root data/FR24_baseline \
  --gold data/rlsm/gold_sample_300.jsonl \
  --output-dir outputs/knowledge_operator_certification/binding_review
```

This writes:

```text
outputs/knowledge_operator_certification/binding_review/
├── binding_candidate_manifest.json
└── binding_review.template.jsonl
```

The candidate denominator is exactly:

```text
300-frame independently reviewed gold screenshot denominator
×
RLSM aircraft observations on those frames
×
union of MFL records discovered by:
    CALLSIGN_EXACT_CASEFOLD
    REGISTRATION_FOLDER_EXACT_CASEFOLD
```

This is an exhaustive denominator **only within those declared discovery rules**. It is not a universal screenshot↔MFL search and it establishes no event identity by itself.

Case folding and trimming are discovery normalization only.

## 5. Review every candidate row

Make a separate reviewed copy:

```bash
cp \
  outputs/knowledge_operator_certification/binding_review/binding_review.template.jsonl \
  outputs/knowledge_operator_certification/binding_review/binding_review.reviewed.jsonl
```

Do not alter these frozen candidate-core fields:

```text
candidate_id
screenshot
aircraft_observation
mfl_record
candidate_basis
candidate_state
schema_version
```

For each row, change `decision` from `UNREVIEWED` to exactly one of:

```text
SAME_EVENT
DIFFERENT_EVENT
UNRESOLVED
```

and fill:

```text
decision_basis[]
independent_evidence_refs[]
reviewed_by
reviewed_at
notes
```

### SAME_EVENT requirements

At least one independent strong basis is mandatory:

```text
DISPLAYED_SOURCE_FLIGHT_ID
NATIVE_TRACK_MATCH
AUTHORITATIVE_SOURCE_LINK
REVIEWED_TIME_ROUTE_CONTINUITY
```

and `independent_evidence_refs` must contain at least one concrete evidence reference.

The following are **insufficient by themselves**:

```text
CALLSIGN_ONLY
REGISTRATION_ONLY
SPATIAL_PROXIMITY
NEAREST_TIME
```

### DIFFERENT_EVENT requirements

At least one of:

```text
NON_OVERLAPPING_TIME
DIFFERENT_SOURCE_FLIGHT_ID
CONTRADICTORY_TRACK
AUTHORITATIVE_EXCLUSION
```

plus at least one concrete independent evidence reference.

### UNRESOLVED

Use when the top evidence remains tied, incomplete, contradictory, or otherwise insufficient. Do not force a deterministic selection to obtain closure.

The binding reviewer must differ from the gold annotator for that screenshot.

## 6. Run the operator-corpus certification

```bash
OUT="outputs/knowledge_operator_certification/$GIT_SHA"

python3 scripts/knowledge_operator_certification.py certify \
  --expected-git-sha "$GIT_SHA" \
  --rlsm-db data/rlsm/rlsm_screenshot_analysis.sqlite \
  --mfl-db data/skywatcher.db \
  --corpus-root data/FR24_baseline \
  --gold data/rlsm/gold_sample_300.jsonl \
  --binding-review \
    outputs/knowledge_operator_certification/binding_review/binding_review.reviewed.jsonl \
  --output-dir "$OUT"
```

The command freezes the reviewed JSONL bytes at start; validates every row against `schemas/knowledge/operator_binding_review.v1.schema.json`; hashes both raw database files and consistent logical SQLite snapshots; re-verifies the 300 source-image bytes and their manifest after audit; re-runs the current RLSM v2 audit; recomputes the candidate denominator from the frozen local databases; verifies that the reviewed file contains the exact candidate set; requires every candidate to have a terminal review decision; requires both positive and negative controls; and writes the reviewed implications to a scratch database only when the review contract itself is not FAIL.

A scratch sidecar is immutable with respect to its frozen input manifest. An identical rerun may reuse it; changed inputs at the same output path fail closed instead of overwriting prior evidence. Use a new output directory for a materially changed review.

A certification run returns:

- exit **0** only for `PASS`;
- exit **2** for `BLOCKED` or `UNRESOLVED`;
- exit **1** for `FAIL` or execution error.

## 7. Output contract

A run writes beneath `$OUT`:

```text
operator_certification_report.json
operator_certification_report.md
operator_sidecar.sqlite
binding_candidate_manifest.json
binding_candidates.recomputed.jsonl
rlsm_audit/
    screenshot_intelligence_audit.json
    screenshot_intelligence_audit.md
    ...
```

Required report claims for any PASS:

```text
inputs_stable_during_certification = true
gold_review.source_byte_failures = 0
gold_review.source_manifest_sha256 = <frozen SHA-256>
candidate_discovery_exhaustive_within_declared_rules = true
candidate_discovery_universal = false
canonical_event_count_changed = false
canonical_mfl_mutation_authorized = false
migration_0004_registered = false
mission_or_intent_established = false
```

The scratch sidecar may contain PASS implications for the **bounded reviewed relation**. It must retain `canonical_event_count = NULL`. A successful relation adjudication does not mutate or increment the MFL event denominator.

## 8. Minimum PASS conditions

All of the following must close simultaneously:

1. frozen Git SHA;
2. RLSM database present and structurally compatible;
3. MFL database present and structurally compatible;
4. exact 300-row independently reviewed gold denominator;
5. current RLSM v2 certification = PASS;
6. candidate denominator recomputes identically;
7. every candidate row reviewed;
8. at least one independently supported SAME_EVENT positive control;
9. at least one independently supported DIFFERENT_EVENT negative control;
10. **zero UNRESOLVED candidate residue inside the bounded candidate denominator**;
11. zero review-core drift or unknown review basis;
12. RLSM/MFL/gold/review and gold-source manifests unchanged during certification;
13. scratch-sidecar foreign-key check = zero failures;
14. canonical MFL mutation remains disabled;
15. migration 0004 remains unregistered.

If any evidence dependency changes after review, regenerate the candidate template. Do not transplant decisions to a changed candidate ID.

## 9. Certification boundary

A PASS establishes only:

> The reviewed screenshot↔MFL relations inside the frozen gold-300, declared-discovery denominator were processed through the provenance-bound implication sidecar without mutating the source authorities, with current RLSM audit PASS and the required positive/negative controls.

It does **not** establish:

- universal screenshot↔MFL completeness;
- a canonical event-count increase;
- mission, intent, coordination, causation, operator identity, or target identity;
- production migration safety on every historical operator database;
- production activation of the implication engine.

Only after this package passes on the operator corpus should PR #332 reconsider migration 0004 registration or active API/GUI wiring.
