# SKYWATCHER SKILL EXECUTION GOVERNANCE SPECIFICATION v1.0.1

**Status:** REVISED DESIGN — PENDING SEPARATE HASH AUTHORIZATION — NO REPOSITORY IMPLEMENTATION AUTHORITY  
**Design date:** 2026-08-03  
**Source archive:** `sw skillpack.zip`  
**Source archive SHA-256:** `1d5f906645e3f9a846e5843d331077b8d2b0f5a3c97aa3b6ed940f8377eff2bd`  
**Linked analytical ontology:** Skywatcher Analytical Ontology v2.0, PR #175 head `24bf57ca40bd2153ff6d428db996fcb27fbc8cb0`  
**Repository mutation:** prohibited by this specification

## 1. Scope and corrected inventory

The supplied archive contains **16 substantive skill packages**, not 12. The 16 source identities are preserved verbatim in `sources/` and as original `.skill` packages in `source_packages/`. The governance design registers **18 canonical target identities** because `satim-flight-gis-evidence` is split into three owner-qualified successors.

This specification adds a **separate linked execution-governance layer**. It does not add an analytical domain, mutate the v2.0 ontology, activate schemas or thresholds, or authorize a repository write.

## 2. Binding relationship to ontology v2.0

Ontology v2.0 remains authoritative for analytical owners and objects:

- Core — shared contracts, provenance, states, registries, normalization, receipts, and validation.
- RLSM — extraction and observation localization.
- SATIM — imagery and terrain interpretation.
- FPIM — flight-path interpretation.
- CORRIM — cross-domain association and reconciliation.
- Legacy — quarantined historical behavior and compatibility.
- Skywatcher — umbrella system and orchestration, not an analytical owner.

Skill governance defines who may activate a bounded responsibility, under what authority, with what inputs, lifecycle, accounting, failure, handoff, receipt, data mode, security, and cadence. Every analytical skill is bound to an explicit set of ontology input/output objects. Unlisted object emission fails closed.

## 3. Source preservation and canonicalization

1. Source skill names, versions, bodies, packages, and hashes are immutable evidence.
2. Canonical skill identities are additive governance records.
3. Source names remain searchable compatibility aliases but cannot override canonical ownership.
4. Historical artifacts are not rewritten in place.
5. Canonical language follows ontology v2.0 even where source skill language differs.
6. Specification provenance (`VERBATIM`, `SPEC_RECOVERED`, `SPEC_RECONSTRUCTED`) is orthogonal to evidence tier T1–T4.

Source tier counts:

| Tier | Source skills |
|---|---:|
| `SPEC_RECONSTRUCTED` | 11 |
| `SPEC_RECOVERED` | 4 |
| `VERBATIM` | 1 |

## 4. Skill identity contract

A canonical skill record requires:

- registry record ID;
- canonical ID, name, and semantic version;
- source identity, version, provenance tier, and hashes;
- successor relation;
- canonical owner and skill class;
- lifecycle state and runtime activation state;
- default cadence and authority ceiling;
- bounded canonical purpose;
- activation and non-activation summaries;
- exact analytical input/output bindings;
- governance outputs and prohibited outputs;
- explicit `mission_or_intent_inference_authorized=false`;
- implementation state.

Canonical owner distribution:

| Owner | Canonical skills |
|---|---:|
| FPIM | 4 |
| Skywatcher orchestration | 3 |
| Core | 2 |
| SATIM | 2 |
| CORRIM | 2 |
| RLSM | 1 |
| CORRIM adapter | 1 |
| Core governance | 1 |
| Meta-governance | 1 |
| Legacy | 1 |

## 5. Lifecycle states

- `DESIGN_REVISED_PENDING_AUTHORIZATION` — corrected canonical design exists; no package hash or runtime is authorized.
- `QUARANTINED_LEGACY` — compatibility-only behavior activated by explicit legacy request.
- `TEMPLATE_ONLY` — non-executable specification template.
- `RETIRED` — retained solely for historical resolution.

Lifecycle is not execution status. Registration or design approval never implies runtime activation.

## 6. Activation policy

A skill may activate only when:

1. the requested responsibility materially matches its canonical purpose;
2. required inputs are present and owner-qualified;
3. required authority is explicitly granted for the run;
4. data mode and security policies admit the inputs;
5. no higher-priority owner conflict remains;
6. the output contract can be satisfied; and
7. activation does not require invented evidence or prohibited analytical promotion.

Activation fails closed. Topical similarity, source aliases, repository access, an orchestrator request, or a prior run do not grant activation or authority.

## 7. Execution authority

Authority is versioned, run-specific, scoped, expiring where applicable, and **non-transitive**. Permissions are evaluated independently for:

- reading sources, repositories, and connected sources;
- generating local artifacts;
- patching a local worktree;
- creating branches, committing, pushing, and opening pull requests;
- sending external communications;
- promoting state or marking review readiness;
- merging, enabling auto-merge, releasing, and destructive writes.

The default design ceiling is read-only plus local artifact generation. All repository, external, promotion, merge, release, and destructive permissions are false unless a separate explicit implementation or execution authorization grants them.

## 8. Execution run and terminal states

A `SKILL_EXECUTION_RUN` records the skill/version, objective, policies, authority, stages, configuration hash, accounting reference, failures, checkpoints, handoffs, and receipt. Nonterminal states are `created`, `validating`, `planned`, and `running`. Terminal skill receipt statuses remain exactly:

- `completed`;
- `partial`;
- `blocked`;
- `failed`.

Completed records and receipts are immutable; corrections create successor records. A cancelled execution run is terminal for linkage purposes and must emit a `blocked` receipt; `cancelled` is not added to the four canonical receipt statuses.

## 9. Input accounting

Every supplied input receives exactly one mutually exclusive disposition:

`total = accepted + rejected + duplicate + review + unresolved`

Output count is separate. A run cannot be `completed` while accounting is unreconciled. Inaccessible, malformed, unsupported, stale, or authority-blocked inputs remain explicitly counted.

## 10. Failure and recovery

A failure record identifies the run, skill, stage, failure class, timestamp, affected records, last valid checkpoint, recoverability, partial artifact references, and smallest corrective action. When completion is impossible, the skill emits a bounded failure packet rather than fabricating completion.

A checkpoint is restart-safe only when bound to input and execution-state hashes and when skill version, configuration, authority, data mode, and security constraints remain compatible.

## 11. Handoffs

A handoff is required when the next interpretation belongs to a different canonical owner. It contains source/destination skills and owners, artifact references, analytical object bindings, unresolved assumptions, reason, status, and required new authority. `authority_transferred` is always false. The destination must obtain its own activation and authority decision.

Examples:

- RLSM `SOURCE_OVERLAY_TRACK_LINE` → FPIM route interpretation.
- SATIM imagery finding + FPIM flight finding → CORRIM association.
- Owner-qualified findings/associations → Skywatcher evidence assembly without new analysis.

## 12. Receipt contract

Every terminal run emits a machine-readable receipt and concise human summary containing:

- status, skill, version, run ID, and timestamp;
- summary and output references;
- input accounting reference;
- evidence and validation references;
- limitations and uncertainty;
- failure and handoff IDs;
- one bounded next action;
- deterministic receipt hash; and
- `mission_or_intent_inference_performed=false`.

The human result may not claim an output absent from the machine receipt.

## 13. Data modes

Permitted modes are `CANONICAL_LIVE`, `AUTHORIZED_ARCHIVED`, `AUTHORIZED_CACHE`, `STALE`, `DEMO`, `SYNTHETIC`, and `UNKNOWN`. Mode is distinct from evidence tier, visibility class, confidence, and provenance. Silent fallback is prohibited. Every fallback requires explicit authorization and disclosure.

## 14. Security

Security classes are `PUBLIC`, `INTERNAL`, `PRIVATE`, `RESTRICTED`, `SECRET_BEARING`, and `CREDENTIAL_BEARING`. Transformation does not lower classification. Secrets and credentials may never be disclosed in receipts or outputs. Policies may require redaction, hash-only references, or restricted retention.

## 15. Cadence

Cadence may be on-demand, weekly-or-on-demand, release-gate, scheduled, event-triggered, or explicit-legacy. A cadence declaration does not create or activate a schedule. All schedules remain disabled in this design.

## 16. Ownership adjudications

### 16.1 Integrated SATIM language

- `satim-engine` → `legacy-integrated-track-visual-analysis-engine`; quarantined Legacy compatibility.
- `satim-engine-operator` → `repo-native-visual-calibration-orchestrator`; **Repo-native Visual Calibration Orchestrator**, non-analytical multi-owner orchestration.
- `satim-flight-gis-evidence` → three successors:
  - `satim-imagery-evidence-analyzer`;
  - `fpim-flight-path-evidence-analyzer`;
  - `corrim-flight-gis-association-analyzer`.

### 16.2 Additional language repairs

- `terrain-access-candidate` → `satim-terrain-feature-candidate-ranker`; no access or operational-suitability claim.
- `aircraft-intelligence-profiler` → `fpim-aircraft-profile-brief`; no derived mission or intent.
- Skywatcher evidence/operator skills become assembly/orchestration only.
- AASB is a CORRIM adapter; ILAP is a CORRIM review-only association object.

## 17. Analytical object binding

The authoritative binding table is `SKYWATCHER_SKILL_OBJECT_IO_MAP_v1_0_1.csv`. The design contains 74 directional bindings. Every row carries `object_term_status`: `ONTOLOGY_CANONICAL` only for subtype labels explicitly frozen by ontology v2.0, or `SKILL_GOVERNANCE_SUBTYPE` for bounded routing labels. Skill-governance subtypes do not extend ontology v2.0 and cannot become analytical schema terms without separate ontology authority. Skills marked `NONE_DIRECT_ANALYTICAL` may emit governance objects only. No skill may emit a claim, operational recommendation, mission, intent, coordination, causation, access, facility purpose, or confirmed landing unless separately authorized by the ontology and independent evidence gates; this package grants no such authority.

## 18. Schema set

The package includes 13 Draft 2020-12 schemas, nine deliberately invalid schema fixtures, and fourteen deliberately invalid semantic fixtures for registry records, provenance, activation, authority, runs, accounting, failures, checkpoints, handoffs, receipts, data mode, security, and cadence. They are design contracts only and are not installed or activated in the repository.

## 19. Implementation sequencing

The path-level plan contains 77 rows:

- SG0-ADDITIVE-GOVERNANCE: 22
- SG1-RUNTIME-FOUNDATION: 15
- SG2-CANONICAL-SKILL-PACKAGES: 19
- SG3-REPOSITORY-INTEGRATION: 9
- SG4-OWNER-DECOMPOSITION: 12

`SG0-ADDITIVE-GOVERNANCE` is the only candidate for a first implementation authorization. It remains blocked until PR #175 is merged, a new exact `main` commit is frozen, every SG0 target is rescanned against that tree, every open pull request is rescanned, and this exact package hash is separately authorized. All overlap values in this design are point-in-time evidence only. SG1–SG4 require separate approvals, current-tree scans, open-PR overlap adjudication, tests, and exact-base verification.

## 20. No-write lock

This design authorizes no repository branch, commit, push, pull request, review promotion, merge, auto-merge, schema activation, runtime activation, threshold activation, scheduled execution, external send, or historical artifact rewrite. PR #175 remains unchanged. A future implementation vector must verify the current repository state and explicitly enumerate an atomic change set.

## 21. v1.0.1 semantic conformance gates

The package validator enforces cross-record rules that JSON Schema cannot express alone:

- exact input-accounting arithmetic;
- authority-to-run and authority-to-skill equality;
- terminal run, receipt, and accounting linkage;
- cancelled run to blocked receipt mapping;
- unique, contiguous, ordered stage sequences;
- completed-run stage consistency;
- checkpoint-to-run, stage, and sequence equality;
- security-classification no-downgrade ordering;
- successor count and registry equality;
- registry-to-I/O binding equality; and
- declared governance outputs for every canonical skill.

Each rule is exercised by at least one deliberately invalid fixture that must fail. Positive examples and the actual registry tables must pass.

## 22. Revision closure and authorization posture

All nine findings in `SKYWATCHER_SKILL_GOVERNANCE_v1_0_REQUIRED_REVISIONS.csv` are closed in `SKYWATCHER_SKILL_GOVERNANCE_v1_0_1_REVISION_CLOSURE.csv`. Technical validation does not authorize repository implementation. SG0 remains deferred; SG1 through SG4 remain blocked.
