# Phase 0 Change Ledger

## Scope lock

- Backend/core only.
- `frontend/` unchanged.
- `data/` unchanged.
- No merge authorized.
- Analytical and schema compatibility preserved.
- No mission/intent inference and no operational cueing added.

## Implemented

| Workstream | Change |
|---|---|
| Repository hygiene | Strict ignore rules, line-ending/binary attributes, tracked-artifact scanner, deterministic source-only exporter |
| Packaging | Root PEP 517 project, `src/skywatcher` package, console entry point, wheel/install smoke gate |
| Dependencies | Removed editable sibling paths; optional federation/desktop packages pinned to exact `thehub-pr` commit |
| Imports | Removed runtime `sys.path.insert`/`append`; retained compatibility facades where needed |
| Test capabilities | Added explicit markers for data, federation, geospatial, OCR, integration, and nested-tool requirements |
| CI | Added Python 3.10–3.13 backend-core matrix plus nested-package jobs |
| Archive safety | Added bounded ZIP extraction with traversal, symlink, encryption, duplicate, size, count, and compression-ratio rejection |
| API security | Writes disabled by default; explicit enable flag plus bearer token required; fixed entity registry and bounded pagination |
| Federation export | Shared helper package remains preferred; exact-compatible local fallback permits standalone core testing |
| Policy | Active aircraft fallback leaves unresolved role unknown; legacy intent inference is quarantined and warning-emitting |
| Documentation | README, federation manifest, module ADR/spec, completion ledger, test evidence, and migration map reconciled |

## Deliberately deferred

- SATIM engine unification beyond the Phase 0 packaging boundary.
- Python ruff/mypy cleanup and coverage floor.
- Frontend tests/typecheck remediation.
- Production data-pack acquisition or mutation.
- Live execution gate changes.
