# FR24 Repo Finalization Operations v1

Active branch: `codex/fr24-visual-parameter-registry-v1`

## Purpose

This document replaces the earlier informal order of operations with a repo-finalization-grade chain for the FR24 visual-analysis subsystem.

The subsystem must not merge as a partial detector collection. It must merge only after the branch has:

- CI enforcement
- versioned parameter contracts
- config/default threshold files
- a shared error/failure taxonomy
- fixture governance
- regression protection
- hub compatibility checks
- release/merge checklist controls

## Architecture Lock

The accepted architecture is:

```text
central registry
→ parameter contracts
→ shared QC/scoring layer
→ parameter-family modules
→ export sidecar mapper
→ audit CLI
→ fixture/regression tests
→ CI and release gate
```

Rejected architectures:

| Architecture | Reason |
|---|---|
| One giant script | too brittle and hard to audit |
| One script per individual parameter | too fragmented |
| Heavy CV/ML first | premature before registry/fixture governance |
| Palm-only detector first | narrow module before shared contract/QC foundation |

## Completion Rule

`FR24 visual v1` is not complete until all operations `00` through `58` are complete, tested, documented, and audit-clean.

## Operations

| Order | Operation | Stage | Required | Current status |
|---:|---|---|---|---|
| 00 | `00_BRANCH_LOCK` — Confirm active development branch and base commit for FR24 visual v1. | foundation_before_parameters | yes | complete |
| 01 | `01_ARCHITECTURE_DECISION_DOC` — Record hybrid architecture: registry + contracts + family modules + audit. | foundation_before_parameters | yes | complete |
| 02 | `02_SCREENSHOT_MODEL` — Create canonical screenshot record and typed fields. | foundation_before_parameters | yes | complete |
| 03 | `03_SCREENSHOT_PROVENANCE` — Add hash, lineage, source platform, timestamp/geometry status. | foundation_before_parameters | yes | complete |
| 04 | `04_SCREENSHOT_PRIVACY_REDACTION_POLICY` — Define screenshot privacy/redaction policy before fixtures. | foundation_before_parameters | yes | in_progress |
| 05 | `05_PARAMETER_CONTRACT_LAYER` — Implement required contract fields for every visual parameter. | foundation_before_parameters | yes | planned |
| 06 | `06_ALLOWED_ENUM_REGISTRY` — Define allowed families, source methods, statuses, export targets. | foundation_before_parameters | yes | planned |
| 07 | `07_CONFIG_DEFAULTS_LAYER` — Move thresholds/defaults to data/reference config. | foundation_before_parameters | yes | planned |
| 08 | `08_VISUAL_QC_ENGINE` — Implement shared confidence, penalty, and review logic. | foundation_before_parameters | yes | planned |
| 09 | `09_ERROR_FAILURE_TAXONOMY` — Standardize extraction and validation failure reasons. | foundation_before_parameters | yes | planned |
| 10 | `10_EXPORT_SIDECAR_CONTRACT` — Define visual sidecar package structure. | foundation_before_parameters | yes | planned |
| 11 | `11_SIDECAR_SCHEMA_VALIDATOR` — Validate sidecar rows independently of base observation schema. | foundation_before_parameters | yes | planned |
| 12 | `12_HUB_COMPATIBILITY_MAPPING` — Map visual rows to observation + sidecar for thehub-pr compatibility. | foundation_before_parameters | yes | planned |
| 13 | `13_PARAMETER_REGISTRY_JSON` — Build machine-readable FR24 visual parameter registry. | parameter_registry | yes | planned |
| 14 | `14_COVERAGE_MATRIX_CSV` — Build coverage matrix for implementation/test/export gaps. | parameter_registry | yes | planned |
| 15 | `15_REGISTRY_DOCS` — Write human-readable parameter registry documentation. | parameter_registry | yes | planned |
| 16 | `16_REGISTRY_LOADER` — Load and validate registry entries. | parameter_registry | yes | planned |
| 17 | `17_AUDIT_CLI` — Add audit CLI for 100% coverage checks. | parameter_registry | yes | complete |
| 18 | `18_PARAMETER_VERSION_FIELD` — Add registry_version and parameter_version controls. | parameter_registry | yes | planned |
| 19 | `19_PARAMETER_DEPRECATION_FIELD` — Add deprecation/replacement policy for UI drift. | parameter_registry | yes | planned |
| 20 | `20_IMPLEMENTATION_MAPPING` — Map parameters to module/function owners. | parameter_registry | yes | planned |
| 21 | `21_TEST_REQUIREMENT_MAPPING` — Map parameters to required fixture/test expectations. | parameter_registry | yes | planned |
| 22 | `22_EXPORT_MAPPING` — Map parameters to observation/sidecar/audit-only/deferred targets. | parameter_registry | yes | planned |
| 23 | `23_REGISTRY_ONLY_AUDIT` — Run contract-completeness audit before implementation. | parameter_registry | yes | planned |
| 24 | `24_UI_CARD_MODULE` — Implement aircraft-card UI family module. | family_modules | yes | planned |
| 25 | `25_TRACK_LINE_MODULE` — Implement track line / ADS-B gap family module. | family_modules | yes | planned |
| 26 | `26_COORDINATE_RECOVERY_MODULE` — Implement coordinate recovery/georeference family module. | family_modules | yes | planned |
| 27 | `27_TEMPORAL_RECONSTRUCTION_MODULE` — Implement time/sequence/replay family module. | family_modules | yes | planned |
| 28 | `28_GROUND_CONTEXT_MODULE` — Implement basemap/ground context family module. | family_modules | yes | planned |
| 29 | `29_PALM_TREE_MODULE` — Implement palm-tree marker family module. | family_modules | yes | planned |
| 30 | `30_INFRASTRUCTURE_CONTEXT_MODULE` — Implement nearest infrastructure/POI context module. | family_modules | yes | planned |
| 31 | `31_OBSERVATION_BUILDER` — Convert parameters into base observation and sidecar rows. | family_modules | yes | planned |
| 32 | `32_BATCH_RUNNER` — Add repeatable screenshot batch-analysis runner. | family_modules | yes | planned |
| 33 | `33_FIXTURE_DIRECTORY_POLICY` — Create fixture layout and naming policy. | fixtures_tests_regression | yes | planned |
| 34 | `34_POSITIVE_FIXTURES` — Add clean positive fixtures. | fixtures_tests_regression | yes | planned |
| 35 | `35_NEGATIVE_FIXTURES` — Add false-positive/suppression fixtures. | fixtures_tests_regression | yes | planned |
| 36 | `36_AMBIGUOUS_FIXTURES` — Add low-confidence/uncertain fixtures. | fixtures_tests_regression | yes | planned |
| 37 | `37_EXPECTED_OUTPUT_JSONS` — Add expected output JSONs for fixtures. | fixtures_tests_regression | yes | planned |
| 38 | `38_UNIT_TESTS_PER_FAMILY` — Add module-level tests per family. | fixtures_tests_regression | yes | planned |
| 39 | `39_CONTRACT_TESTS` — Add tests enforcing registry contracts. | fixtures_tests_regression | yes | planned |
| 40 | `40_QC_SCORING_TESTS` — Add tests locking confidence math. | fixtures_tests_regression | yes | planned |
| 41 | `41_EXPORT_SIDECAR_TESTS` — Add sidecar validation tests. | fixtures_tests_regression | yes | planned |
| 42 | `42_REGRESSION_SNAPSHOT_TESTS` — Add snapshot tests for scoring/output drift. | fixtures_tests_regression | yes | planned |
| 43 | `43_EXISTING_TEST_SUITE_CHECK` — Confirm existing airspace tests still pass. | fixtures_tests_regression | yes | planned |
| 44 | `44_CI_WORKFLOW_AUDIT_GATE` — Add CI gate for tests + FR24 finalization audit. | ci_docs_finalization | yes | complete |
| 45 | `45_README_AUDIT_COMMAND` — Add repeatable audit commands to README/docs. | ci_docs_finalization | yes | planned |
| 46 | `46_FR24_WORKFLOW_DOC` — Add operational screenshot workflow doc. | ci_docs_finalization | yes | planned |
| 47 | `47_VISUAL_PARAMETER_DOCS` — Add full visual parameter documentation. | ci_docs_finalization | yes | planned |
| 48 | `48_SIDECAR_EXPORT_DOCS` — Add visual sidecar docs. | ci_docs_finalization | yes | planned |
| 49 | `49_PALM_PARAMETER_DOCS` — Add palm-specific calibration docs. | ci_docs_finalization | yes | planned |
| 50 | `50_CHANGELOG_ENTRY` — Add v1 changelog entry. | ci_docs_finalization | yes | planned |
| 51 | `51_RELEASE_CHECKLIST` — Add merge/release checklist. | ci_docs_finalization | yes | complete |
| 52 | `52_FULL_LOCAL_TEST_SUITE` — Run full pytest suite locally/CI. | ci_docs_finalization | yes | planned |
| 53 | `53_REGISTRY_AUDIT_RUN` — Run 100% required parameter audit. | ci_docs_finalization | yes | planned |
| 54 | `54_SIDECAR_VALIDATION_RUN` — Run sidecar validation on fixture outputs. | ci_docs_finalization | yes | planned |
| 55 | `55_HUB_COMPATIBILITY_CHECK` — Validate federation compatibility with hub mapping. | ci_docs_finalization | yes | planned |
| 56 | `56_BASELINE_BRANCH_COMPARE` — Compare against main for unrelated drift. | ci_docs_finalization | yes | planned |
| 57 | `57_PR_SUMMARY` — Prepare reviewable PR summary. | ci_docs_finalization | yes | planned |
| 58 | `58_MERGE_READY_TAG` — Tag or mark FR24 visual v1 as merge-ready after validation. | ci_docs_finalization | yes | planned |

## Hardening Layers Added to the Order

| Layer | Requirement |
|---|---|
| CI | `pytest` and FR24 audit must run in GitHub Actions before merge |
| Versioning | registries and contracts must carry explicit version fields |
| Config defaults | thresholds must live in data/reference config, not only detector code |
| Error taxonomy | extraction failures must use controlled names |
| Fixture policy | screenshots and expected outputs must follow a stable directory/naming policy |
| Regression tests | scoring/output drift must be detected by snapshots or equivalent locked expectations |
| Hub compatibility | base observation exports must remain compatible with the federation export contract |
| Release checklist | final merge requires a checklist, not informal confidence |

## Required Gates

| Gate | Pass condition |
|---|---|
| Foundation gate | screenshot identity, provenance, contracts, enums, defaults, QC, error taxonomy, sidecar contract, and hub mapping exist |
| Registry gate | registry, matrix, docs, loader, audit CLI, version/deprecation fields, implementation/test/export mappings exist |
| Family gate | all required parameter families are implemented or explicitly deferred |
| Fixture gate | positive, negative, ambiguous, expected-output, and regression fixtures exist |
| CI gate | tests and FR24 finalization audit run automatically |
| Finalization gate | full tests, registry audit, sidecar validation, hub compatibility check, baseline comparison, and PR summary are complete |

## No-Drift Rule

New FR24 visual parameters must be added to the central registry first. Detector modules cannot introduce ad hoc parameter names.
