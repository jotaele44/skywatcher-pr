# Phase 0 Change Ledger

## Scope lock

- Backend/core hardening authored in this phase.
- No remediation-authored changes under `frontend/` or `data/`.
- Current-main frontend changes are preserved byte-for-byte through merge parents.
- No merge authorized; PR remains draft.
- Analytical schemas remain compatible.
- Mission, intent, target, wrongdoing, causality, and operational-purpose inference are prohibited.
- `operational_cueing=false` remains enforced.

## Implemented

| Workstream | Change |
|---|---|
| Main synchronization | Current `main` is a true merge parent; CodeQL, secret scan, pip-audit, Dependabot, pre-commit, Ruff, mypy, coverage, pinned Actions, and frontend checks are preserved |
| Repository hygiene | Canonical policy shared by tracked-artifact scanning and deterministic source export; generated build, wheel, coverage, maintenance, cache, archive, and runtime paths are rejected |
| Packaging | Root PEP 517 project, canonical `src/skywatcher` package, compatibility facades, and `skywatcher` console entry point |
| Installed CLI | Repository assets are explicit; schema validation fails when schemas are absent or zero; runtime writability is tested rather than inferred |
| Isolated wheel gate | Wheel is installed into a clean virtual environment and exercised from an empty directory before explicit-root validation |
| Dependencies | Mutable sibling clones and editable sibling paths removed; federation and desktop packages use exact TheHub commit references; lock resolution is reverified in CI |
| Imports | Runtime `sys.path.insert`/`append` removed while compatibility import paths remain |
| Test capabilities | Data-independent core and full-data coverage are separate gates; external-service, federation, geo, OCR, and tool-package markers remain explicit |
| Coverage | Preserved 55% full-repository floor; full CI includes data-capability tests while backend-core remains data-independent |
| Archive safety | Validation-first, streamed byte limits, Windows alias rejection, symlink/encryption/duplicate/ratio checks, default no-replace, backup promotion, and rollback |
| Archive parity | Core and distributable SATIM packages implement the same extraction contract and defaults |
| API security | Writes disabled by default; explicit enable flag and bearer token required; server-owned immutable IDs; reserved-field rejection; payload and page bounds |
| Aircraft identity | Exact normalized identifiers only; explicit aliases; unverified legacy entries expose no owner/operator/role fields |
| Provenance | Identity enrichment requires field-level source URI, record ID, capture time, and SHA-256 before promotion |
| No-intent policy | Active profiles always leave role unresolved, omit mission lists, and expose no typical hours or high-activity-region cueing |
| Federation export | Preferred shared helper remains exact-pinned; compatible local fallback permits standalone core validation |
| Source export | Deterministic timestamps and ordering plus preservation of executable launcher modes |
| Documentation | README, completion ledger, evidence, migration map, remediation ledger, and review closure report reconciled |

## Deferred beyond Phase 0

- Selection of one canonical SATIM implementation beyond the hardened package boundary.
- Gating the existing Ruff/mypy backlog after incremental cleanup; both remain visible in CI.
- Production data acquisition, mutation, or live-execution readiness changes.
- Durable multi-user review storage; the current diagnostic overlay remains process-scoped.
- Removal of compatibility facades after a defined deprecation window.
