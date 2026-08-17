# skywatcher-pr — Professional Maturity Audit

**Date:** 2026-07-26 · **Method:** static review **plus execution** — every number below came
from running the code in a clean container (Python 3.11.15, Node v22.22.2). Setup followed
this repo's own `hub_callable_commands.setup`.

Scope: this repository only. Cross-repo comparisons live in
[`thehub-pr/docs/FEDERATION_MATURITY_AUDIT.md`](https://github.com/jotaele44/thehub-pr/blob/main/docs/FEDERATION_MATURITY_AUDIT.md).

---

## Scorecard

| Dim | Area | Score | Evidence |
|---|---|---|---|
| D1 | Functional completeness | **3** | FR24 ingest (13.7k LOC), RLSM suite, SATIM/FPIM/CORRIM engines all real; auth surface was dead (fixed below) |
| D2 | Data reality | **1** | Self-declared `NON_PRODUCTION_DIAGNOSTIC`; the only export package is `synthetic_airspace_package`. Real asset: 19 FAA-sourced PR airports. |
| D3 | UI craft | **4** | 15 pages, 8.8k LOC; the richest component library in the federation — 8 detail drawers, `LoadingState`, `EmptyState`, `SyntheticDataBadge`, `SourceProvenanceBadge`. 45 `aria-*` usages, highest of any node. |
| D4 | Test coverage | **3** | `807 passed, 13 skipped` (13.6s) — 101 test files, second-largest suite. But **zero frontend tests** for 8.8k LOC of UI. |
| D5 | Engineering hygiene | **1** | **No ruff and no mypy in any workflow.** `ruff check .` → 247 findings; `npm run typecheck` → 229 errors, run by nothing. |
| D6 | Doc accuracy | **4** | 148 markdown files including per-module specs and ADRs; `federation.json` blockers are honest and specific |

**Overall: strong engine, excellent UI, and almost no automated quality gate holding either
in place.** This repo's `federation.json` is candid about its data gap — that honesty is a
genuine strength and the audit takes it at face value. The unguarded lint/type surface is
the real risk: 51.5k LOC of Python and 8.8k of JSX with nothing enforcing consistency.

---

## What is fully developed vs. what is not

**PRODUCTION**

| Module | Evidence |
|---|---|
| `fr24/` (69 files, 13,722 LOC) | screenshot inventory, ensemble OCR, RLSM/route extraction, manual-review queue, event export; stdlib-only core |
| `src/skywatcher/core/readiness_engine.py`, `prii_readiness_engine.py` | covered by three dedicated test modules including an equivalence test between the two |
| `scripts/rlsm_*.py` | route-line-segment mining backed by `pipeline/` normalization + ontology gate, `configs/*.yaml` registries, `data/rlsm/schema.sql` |
| `data/reference/pr_airports.jsonl` | 19 real PR airports (FAA NASR + Airport_Master_PR seed) — the repo's one unambiguously real dataset |
| Export contract | `scripts/validate_airspace_export.py` + two JSON schemas, CI-validated |
| `server/backend/main.py` | 13 routes over committed artifacts; repo files never mutated (in-memory overlay by design) |

**FUNCTIONAL**

| Module | Gap |
|---|---|
| `frontend/` (15 pages, 8.8k LOC) | no test file of any kind; no test runner in `package.json` |
| `scripts/` (53 files, 10,306 LOC) | more than twice the LOC of `src/` (4,343); loose scripts are harder to test and import than package modules |
| `imagery/`, `tools/` | present and working, outside the enforced-lint set (which is empty) |

**SCAFFOLD**

| Item | Why |
|---|---|
| `gebco/` terrain layer | requires `requirements-geo.txt` (numpy/scipy/xarray/netCDF4); optional, not in the default path |
| Canonical export adapter | `scripts/federation_export.py` projects observations → entities/sources/relationships, but has only synthetic observations to project |
| ILAP intake | needs FlightRadar24 screenshots supplied locally — an external data gap, correctly declared |

**DEAD** — *fixed in this PR.*

| Item | Proof |
|---|---|
| Login / Register / ForgotPassword / ResetPassword | `federationClient.js` posts to `/auth/login`, `/auth/register`, `/auth/verify-otp`, `/auth/password/reset-request`, `/auth/password/reset`, `/auth/resend-otp`. **All six returned HTTP 404** against a live server. `/api/auth/me` → 401 `"No auth in local diagnostic mode"`. `App.jsx` had no `ProtectedRoute` at all, so nothing was gated and the forms could never succeed. |

---

## UI feature matrix

| Page | Backing data | States handled | Verdict |
|---|---|---|---|
| Dashboard | `useSkywatcher` over `/api/entities/*` | loading, synthetic badge, blockers | **Functional** — renders synthetic observations, clearly labelled |
| Observations, Aircraft, Routes, Airports | entity API over committed artifacts | loading, empty | **Functional**; Airports is the only page on fully real data |
| FR24Intake, ManualReview, Calibration | review queue + SATIM summaries | loading, empty, review actions | **Functional** (session-scoped edits) |
| Infrastructure, ExportCenter, Readiness | export manifests, readiness reports | loading, empty | **Functional** |
| AnalysisLenses | `/api/analysis/registry` + `AnalysisLenses`/`AnalysisObjectives`/`LensCoverage` | loading, empty, registry-unavailable, fetch failure | **Functional** — the only page whose vocabulary is fetched rather than hardcoded |
| Login, Register, ForgotPassword, ResetPassword | none | — | **Dead**, now gated |

`AnalysisLenses` is worth a note for a different reason: every other page in this table
hardcodes its analytical vocabulary as JSX literals (`REVIEW_STATUS`, `INGEST_STATUS`, the
per-page filter option lists), so a backend change needs a matching frontend edit or the
two drift silently. That page fetches the registry instead, and
`tests/test_analysis_registry_gui_parity.py` asserts no lens id appears in its source.
That test also compares the backend `LOADERS` map against the frontend `ENTITIES` map,
which closes a long-standing gap — the two are hand-maintained mirrors that nothing
compared, and `Promise.allSettled` in `SkywatcherData.jsx` turns a missing entity into a
silently empty table rather than an error.

`SyntheticDataBadge` and `DiagnosticNoticeBanner` are worth calling out: the UI tells the
operator when it is showing synthetic data. That is the correct behaviour and several
sibling repos do not do it.

---

## Fixes applied in this PR

**1. Auth routes render only when auth is required.**
`frontend/src/App.jsx` now computes `authRequired` from
`appPublicSettings?.public_settings?.requires_auth || appParams.requireAuth` — the exact
expression `lib/AuthContext.jsx:53-55` already uses — and redirects `/login`, `/register`,
`/forgot-password`, `/reset-password` to `/` when auth is off. The pages remain wired for
the day a real `/auth/*` backend exists; they simply stop offering a sign-in that 404s.

**2. Mutating API routes refuse unauthenticated non-loopback callers.**
`server/backend/main.py` gains `require_write_access` on `POST /api/entities/{name}` and
`PATCH /api/entities/{name}/{id}`:

- `PRII_WRITE_TOKEN` set → bearer token required (`secrets.compare_digest`)
- unset → writes served to loopback only, with a startup warning

`POST /api/entities/{name}/filter` is deliberately **not** guarded — despite the verb it is
a read. Verified against a live server bound to `0.0.0.0`, probed from a non-loopback address:

| Condition | Expected | Observed |
|---|---|---|
| no token, loopback write | 200 | **200** |
| no token, remote write | 403 | **403** |
| no token, remote **read** | 200 | **200** |
| token set, correct bearer | 200 | **200** |
| token set, wrong bearer | 401 | **401** |
| token set, no bearer | 401 | **401** |

The overlay is in-memory and never reaches disk, so the blast radius was always one process
— but every reader of a shared instance saw another client's unauthenticated edits.

Regression check: `npm run lint` clean, `npm run build` clean, `npm run typecheck` 229
errors **before and after** (identical — these changes add none), `pytest` unchanged.

---

## Backlog, ranked

| # | Item | Effort | Why it matters |
|---|---|---|---|
| 1 | Add ruff + mypy to CI | **M** | The largest gap here. 247 ruff findings and 51.5k LOC with no enforced standard. Start by gating new/changed files so the backlog does not block the build. |
| 2 | `_ocr_regions` crashes when `pytesseract` is installed but the `tesseract` binary is absent | **S** | `fr24_image_skill/orchestrator.py:188-190` catches `ImportError` for the Python package but not `pytesseract.TesseractNotFoundError` for the binary. Proven: with `pytesseract` present and no binary, 6 tests in `tests/test_fr24_image_skill.py` fail instead of degrading to the `dependency_unavailable` row the code clearly intends. CI does not install `pytesseract`, so CI stays green and this only bites real users. |
| 3 | Add a frontend test runner and smoke tests | **M** | 8.8k LOC of UI, 15 pages, zero tests. `thehub-pr` has a working vitest + Testing Library + `vitest-axe` setup to copy. |
| 4 | Run `npm run typecheck` in CI, or drop the script | **M** | 229 errors, enforced by nothing. |
| 5 | Land a non-synthetic observation export | **L** | The repo's own top blocker. Everything downstream — live execution, real correlation — waits on it. |
| 6 | Move reusable logic from `scripts/` into `src/skywatcher/` | **L** | `scripts/` is 10,306 LOC vs `src/` 4,343. Script-resident logic is hard to import, test, and lint. |
| 7 | Reconcile `requires_auth` vs `auth_required` key naming with `centinelas-pr` | **S** | Same concept, two keys, across one federation. |

---

## Maturity score — 61%

Measured 2026-07-27 against 20 explicit criteria (5 points each, 100 total). Every
lost point is a specific, verifiable work item, so this doubles as the roadmap.

| Dimension | Score | Criteria (5 pts each) |
|---|---|---|
| Functional completeness | **17/20** | backend serves domain · no dead UI · entrypoints work · modules wired, no duplicate mass |
| Data reality | **6/20** | real non-synthetic dataset · refresh automated · offline bundle populated · live-exec gate open |
| UI craft | **17/20** | pages proportionate to backend · loading+empty+error everywhere · a11y markup **and** automated gate · single consolidated frontend |
| Tests | **5/15** | suite green · coverage gate enforced · frontend tests run in CI |
| Hygiene | **5.5/15** | linters gated in CI · type checking gated in CI · write surface secured *and* client can use it |
| Docs | **10/10** | docs match code · declared status matches observed maturity |
| **Total** | **60.5/100** | |

### How the score is computed

20 criteria, 5 points each, 100 total. **Partial credit is allowed** where a criterion
splits cleanly into independent halves — for example "linters gated in CI" scores 2.5 for
Python and 2.5 for JavaScript, so a repo that gates one and not the other scores 2.5. That
is why dimension totals are not always multiples of five.

Components here sum to **60.5** (17 + 6 + 17 + 5 + 5.5 + 10), reported as **61%**. Half-points are
rounded **half up** to the nearest whole percent for the cross-repo table; the exact figure is the one
above.

The earlier 0–4 per-dimension scorecard above is retained for cross-repo comparison,
but it saturates — `aguayluz-pr` scored 24/24 on it while still having no frontend
tests. This finer model is the one to plan against.
