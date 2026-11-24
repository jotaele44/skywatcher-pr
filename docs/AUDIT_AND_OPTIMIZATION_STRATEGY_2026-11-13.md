# skywatcher-pr — audit against desired outcome, and optimization strategy (2026-11-13)

**Audit date:** 2026-11-13 · **`main` at audit:** `0c0b5c8` · **Production status:** `NON_PRODUCTION_DIAGNOSTIC`

This is a dated snapshot. It compares the repository with the outcome the repository itself declares, then gives an ordered strategy to close the gap. It supersedes the priorities in `docs/BLOCKERS_AND_UNBLOCK_PLAN_2026-09-28.md`; the blocker IDs (`SK-nn`) are kept from that document.

## Desired outcome

The repo states its target in three places, and they agree:

- `federation.json`: `federation_readiness_gate.ready_for_hub_live_execution` is `true`. Today it is `false`, with four blocking conditions.
- `docs/ROAD_TO_100.md` and `docs/unfinished_implementation_ledger.v1.json`: a normalized score of 100. It was last scored at 65.05 on 2026-08-04.
- The README operating contract: source-family gates closed and certification on frozen real data. Passing code and tests does not count as certification.

## How this audit was built

Checks run on `0c0b5c8`:

- `ruff check .`
- `python3 tools/check_docs_sync.py --base origin/main`
- `python3 scripts/check_gui_parity.py`
- `python3 .federation/check_admin_boundary.py`
- the open pull request, open issue and Actions run listings on GitHub

Not run: `pytest` and the frontend build. Their status below is taken from CI on `main`. Not verifiable with the access used: the operator's local corpora, Actions secrets, and the code-scanning and Dependabot alert inventories.

## Current state

### In good shape

| Area | Evidence |
|---|---|
| `main` is green | All 9 push workflows passed on `0c0b5c8`; the scheduled `adsb-poll` and GUI parity runs are green |
| Lint and governance gates | `ruff` clean; docs-sync 0 violations; admin boundary pass over 719 files; GUI parity pass with 0 new unmapped candidates |
| Earlier findings fixed | The missing-Tesseract-binary crash is handled in `fr24_image_skill/orchestrator.py`; the frontend has 21 test files; `server/backend/console/` is populated |
| Honest self-reporting | `federation.json` blocking conditions, the synthetic-data badges and the console capability statuses describe the gaps accurately |

### The gap

**1. The readiness gate has not moved since June.** Issue #7 (non-synthetic FR24 export) was opened on 2026-06-12 and is still the top blocker. Of the 13 blockers recorded on 2026-09-28, one is closed (SK-13, corrected alongside this document) and the rest are open, including the ones that need no operator data:

| Blocker | State on 2026-11-13 |
|---|---|
| SK-10 stale vendored schema | `schemas/federation_entity.schema.json` still requires `location.lat` and `location.lon`; no schema carries `is_critical` |
| SK-04 `places.geojson` dependency | Still read by `scripts/rlsm_spatial_map.py` and `scripts/rlsm_diacritic_repoi.py`, although the README says the file is not required |
| SK-03 packaging certification | No receipt and no workflow |
| SK-01, SK-02, SK-05, SK-06, SK-07 | Operator- or data-gated; unchanged |
| SK-08 (#279), SK-09 (#240), SK-12 | Open; no linked work merged |
| SK-11 open pull requests | Worse; see point 3 |

**2. Feature breadth is outrunning the gate.** Since the September audit, `main` gained the Sky Target Finder, Sky Cameras, the Pitirre foundation, Space-Track reconciliation and PR Grid V2, and #366 proposes a live ADS-B map. None of these retires a readiness blocking condition. The README contract describes a sky-domain analysis plane, while `federation.json` declares `airspace_intelligence_node`.

**3. Work in progress is piling up.**

| Queue | 2026-09-28 | 2026-11-13 |
|---|---:|---:|
| Open pull requests | 17 | 28 |
| of which drafts | 2 | 12 |
| of which dependabot | 11 | 11 (9 untouched since 2026-09-21) |
| Remote branches | 52 | 78 |
| Open issues | 4 | 5 |

The September plan's first priority was to rebase #324 and merge the green dependabot pull requests. #324, #299, #308 and #314 are all still open.

**4. Several gates report but do not block.**

| Gate | State |
|---|---|
| `mypy` | `continue-on-error` in `ci.yml` |
| `npm run typecheck` | Not run in CI; 229 errors at the last recorded count |
| Secret scan, `pip-audit` findings | Report-only |
| GUI parity | Ratchet mode: 395 of 2,291 candidates are mapped; 1,896 (83%) sit in the legacy baseline |
| Coverage | Floor of 55% |

**5. Structure is drifting the wrong way.** `scripts/` grew from 53 files and 10.3k lines (July audit) to 85 files and 16.7k lines; that audit asked for it to shrink. `server/backend/main.py` grew from 841 to 1,599 lines. The console capability registry has 24 entries: 4 available, 3 degraded and 17 unavailable, on a dashboard that ADR 0001 calls diagnostic-only.

**6. The status documents were stale.** The ledger and `docs/ROAD_TO_100.md` were dated 2026-08-04 and `AUDIT.md` 2026-09-21. They are exempt from docs-sync, so nothing forces them current. This change refreshes their item states; the 65.05 score is marked superseded and not re-scored.

## Strategy

One rule sets the order: **until the readiness gate flips, a change earns priority by retiring a named blocker, not by adding surface.** The work is split into five waves, each a separate pull request or small set, so that nothing waits on operator data unless it has to.

### Wave 0 — reset the source of truth

Done in the change that adds this document: this audit, the `AUDIT.md` correction (SK-13), refreshed ledger and roadmap states, and a README note that `federation.json` is the authority for role and readiness.

### Wave 1 — drain the queues

- Dependabot: merge the green grouped and minor pull requests (#370, #314, #308). For the majors (#304 to #307, #310, #312, #315), either migrate or ignore the major. `.github/dependabot.yml` and the action pins (#311, #313) are rendered from thehub-pr templates, so those changes go through the hub and a re-render.
- Own pull requests: rebase and land, or close, the five non-drafts (#299, #324, #353, #360, #366). Give each of the 12 drafts one disposition: land, close with the branch kept under `archive/`, or convert to an issue.
- Branches: prune merged, `tmp*` and `rescue*` branches; keep `freeze/*` and `archive/*`.
- Afterwards, hold a standing limit of 5 open non-dependabot pull requests.

### Wave 2 — make the reporting gates block, by ratchet

- `mypy`: fix the findings in `src/skywatcher`, then drop `continue-on-error`.
- `tsc`: run `npm run typecheck` in the `frontend` job against an error-count ceiling that can only fall.
- Secret scan: triage the baseline, then drop `continue-on-error`, as the workflow's own comment prescribes.
- Coverage: raise `fail_under` to just below the measured value.
- GUI parity: add a ceiling on the legacy count (1,896) so the unmapped baseline can only shrink.

### Wave 3 — the critical path to live readiness

Executable without operator data:

- SK-10: re-vendor the hub entity and alert schemas at the pinned hub commit, with a test that ingests a hub-valid package with 0 rejects.
- SK-04: move the two `places.geojson` readers onto `data/reference/Gazetteer_PR_GNIS.gpkg` and the RLSM geo anchors, failing closed with zero keys.
- SK-03: a manually dispatched job that installs, tests and packages from a clean clone and emits a certification receipt.
- Issue #7, code half: the airfield, helipad and hangar registries and endpoint attribution, built and tested on fixtures, so the real export is one command once captures exist.
- SK-07: dispatch the frozen NOAA Maria pilot fetch from a network-enabled runner.

Operator inputs, which nothing in the repository can substitute for:

1. The full local screenshot corpus run (SK-01) and replay receipts (SK-02).
2. Licensed or authorized FR24 captures (SK-05), then `python scripts/validate_airspace_export.py <package> --mode production`.
3. The media-identity adjudication and capture-geometry review named in `federation.json`.

The gate flips only on receipt evidence from these three.

### Wave 4 — structure

- Move reusable logic from `scripts/` into `src/skywatcher/`, leaving thin command-line wrappers. Start with the `rlsm_*` scripts touched in Wave 3.
- Split `server/backend/main.py` into routers, following `server/backend/console/router.py`.
- Console capabilities: retire or hide the 17 unavailable entries instead of building adapters, because the hub is the supported product surface (ADR 0001). This reverses item 4 of `docs/BACKEND_ASSESSMENT_AND_DEVELOPMENT_PLAN.md` and needs a maintainer decision.

## Maintainer decisions

- Whether to adopt the breadth freeze until the gate flips.
- SG0: re-ballot it or retire the skill-governance track (SK-12).
- Branch protection on `main`.
- Build or retire the unavailable console capabilities.
