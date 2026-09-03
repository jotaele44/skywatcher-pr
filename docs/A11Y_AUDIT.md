# Accessibility (a11y) Audit — Skywatcher-PR

Audit date: 2026-08-24
Scope: `frontend/` (React/Vite SPA), live-rendered against the repo's own read-only
diagnostic backend. Follows up on `docs/GUI_AUDIT.md` (2026-08-23) with a live axe-core +
keyboard/touch-target pass and a design-system-usage inventory (`docs/design-system-usage.json`).

## Overview

Skywatcher-PR ships as a `NON_PRODUCTION_DIAGNOSTIC` dashboard with `requires_auth: false`
(`GET /api/apps/public-settings`). This audit exercised the real running app — Vite dev
server in front of the FastAPI backend — rather than static source reading, using the
shared federation a11y runner (Playwright + axe-core) pinned across the sibling repos.

**Headline results.** Across the 5 routes audited, every route fails at least one check on
the 390×844 mobile viewport; 2 of 5 also fail on 1280×800 desktop. The failures are not
scattered — they trace back to **three concrete, reusable root causes**, all in shared
layout/primitive code rather than page-specific markup (see Findings). Fixing those three
would clear the large majority of violations found across all 5 routes and, by extension,
very likely across the other 8 unaudited reachable routes too, since they share the same
`Layout.jsx` shell and `Checkbox` primitive.

## Method

- **Runner:** the shared `/home/user/.a11y-runner` harness — pinned `@playwright/test`
  1.62.1 + `@axe-core/playwright` 4.12.1, explicit Chromium executablePath (Chromium
  141.0.7390.37), not modified for this audit. It waits for `networkidle` + a fixed 800ms
  settle before every check specifically to avoid the hydration-race false-pass bug that
  affected earlier runs of this class of tool; that fix was already in place and was
  trusted as-is here.
- **App under test:** backend `python -m uvicorn server.backend.main:app --port 8104`
  (FastAPI 0.141.1, read-only diagnostic mode, `PRII_WRITE_TOKEN` unset); frontend
  `VITE_API_PROXY_TARGET=http://localhost:8104 npx vite --port 5304` (Vite 6, React 18.2,
  react-router-dom 6.26). Vite's dev proxy forwards `/api/*` to the backend server-side, so
  no CORS configuration was needed and no source file was patched to test this — confirmed
  by `curl http://127.0.0.1:5304/api/apps/public-settings` returning the backend's payload
  through the Vite origin.
- **Checks per route, per viewport:** axe-core violation scan (filtered to `critical`/
  `serious` impact), one visible-focus check after a single `Tab` press, a horizontal-
  overflow check, and a touch-target sweep of all visible `<button>` elements (44px minimum
  height).
- **Viewports:** `390×844` (mobile-compact) and `1280×800` (desktop-1280). Both were run for
  every route.
- **Theme:** only one theme was tested, because only one exists. `frontend/src/index.css`
  defines identical dark HSL values under both `:root` and `.dark`, and
  `frontend/src/main.jsx` hardcodes `document.documentElement.dataset.theme = 'dark'` with
  no toggle in the UI and no light palette to switch to anywhere in the stylesheet. There is
  no dark-vs-light comparison to make here — see `docs/design-system-usage.json` →
  `themeSupport`.
- **Route subset — stated explicitly, not silently.** Skywatcher-PR has the largest page
  catalog in the PRII family: 17 files under `frontend/src/pages` (19 including the 2
  `.test.jsx` files), of which 13 are reachable without auth in this diagnostic build (the
  other 4 — Login/Register/ForgotPassword/ResetPassword — redirect to `/` because
  `requires_auth: false`, per `docs/GUI_AUDIT.md`). **This audit live-tested 5 of those 13
  reachable routes (~38%): `/` (Dashboard), `/observations`, `/review` (Manual Review),
  `/calibration` (SATIM Calibration), and `/analysis` (Analysis Lenses).** That is a
  materially smaller fraction of this repo's surface than a same-sized subset would cover
  in a smaller sibling repo, and it is a deliberate, bounded sample, not full coverage — see
  Scope limitations. `/analysis` was chosen as the "one more" route over the other 8
  untested reachable pages (`/aircraft`, `/fr24`, `/routes`, `/infrastructure`, `/airports`,
  `/export`, `/readiness`, `/spatial-truth`) because it is the one route present in
  `Sidebar.jsx`'s nav list that is *not* mentioned in `docs/GUI_AUDIT.md`'s 12-link sidebar
  count — i.e. it was added to this app after the last GUI audit, making it the least
  previously-scrutinized reachable page.

## Per-route results

| Route | Viewport | axe (critical/serious) | Keyboard focus visible | No horiz. overflow | Touch targets ≥44px |
|---|---|---|---|---|---|
| `/` | mobile 390×844 | **FAIL** — `button-name` (critical), `scrollable-region-focusable` (serious, ×2 nodes) | pass | pass | **FAIL** — 1 button @32px |
| `/` | desktop 1280×800 | **FAIL** — `scrollable-region-focusable` (serious, `main`) | pass | pass | pass |
| `/observations` | mobile 390×844 | **FAIL** — `button-name` (critical), `scrollable-region-focusable` (serious) | pass | pass | **FAIL** — 4 buttons (1 @32px, 3 @16px) |
| `/observations` | desktop 1280×800 | pass | pass | pass | **FAIL** — 3 buttons @16px |
| `/review` | mobile 390×844 | **FAIL** — `button-name` (critical), `scrollable-region-focusable` (serious, ×2 nodes) | pass | pass | **FAIL** — 1 button @32px |
| `/review` | desktop 1280×800 | pass | pass | pass | pass |
| `/calibration` | mobile 390×844 | **FAIL** — `button-name` (critical), `scrollable-region-focusable` (serious, ×4 nodes incl. a horizontally-scrolling table wrapper) | pass | pass | **FAIL** — 1 button @32px |
| `/calibration` | desktop 1280×800 | **FAIL** — `scrollable-region-focusable` (serious, `main`) | pass | pass | pass |
| `/analysis` | mobile 390×844 | **FAIL** — `button-name` (critical), `scrollable-region-focusable` (serious) | pass | pass | **FAIL** — 1 button @32px |
| `/analysis` | desktop 1280×800 | pass | pass | pass | pass |

Raw Playwright JSON results for each route are preserved for reference at
`/tmp/claude-0/-home-user/e6936745-1952-5ad8-b702-f6cd292a7ab9/scratchpad/a11y-results/results-*.json`
(session-local scratch path, not committed).

Keyboard-focus-visible and no-horizontal-overflow passed on every route/viewport combination
tested — no findings there.

## Findings (prioritized)

### 1. [Critical] Unlabeled mobile-nav toggle button — fails `button-name` and touch-target on every route

`frontend/src/components/skywatcher/Layout.jsx`:

```jsx
<button
  onClick={() => setMobileOpen((v) => !v)}
  className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-secondary text-foreground"
>
  {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
</button>
```

This is the hamburger/close toggle for the mobile nav, visible only below the `md`
breakpoint. It has no visible text, `aria-label`, or `title`, so axe's `button-name` rule
(WCAG 4.1.2, critical impact) fires on **every route at the mobile viewport** — this is the
single highest-multiplicity finding in the audit, appearing identically 5/5 times. The same
element is also 32×32px (`h-8 w-8`), under the 44px touch-target minimum, so it double-counts
as a touch-target failure everywhere too. Fix: add `aria-label={mobileOpen ? "Close navigation" : "Open navigation"}` and increase the hit area to at least 44×44px (padding, or `h-11 w-11`).

### 2. [Serious] Scrollable regions have no keyboard access — `main`, the sidebar `nav`, and (on `/calibration`) a table wrapper

`scrollable-region-focusable` (WCAG 2.1.1) fired on:
- `<main className="flex-1 overflow-y-auto scrollbar-thin">` in `Layout.jsx` — whenever a
  page's content actually overflows the viewport (desktop: `/` and `/calibration`; mobile:
  every route, because the mobile nav overlay pushes/obscures the layout).
- `<nav className="flex-1 space-y-0.5 overflow-y-auto p-2 scrollbar-thin">` in
  `Sidebar.jsx` (matched via its `.z-30` ancestor) — the sidebar item list, on mobile where
  the overlay sidebar renders.
- On `/calibration` specifically, an additional `.overflow-x-auto.scrollbar-thin.border`
  table wrapper (a horizontally-scrolling data table) was also flagged, on top of `main` and
  the sidebar nav — the most nodes-per-route of any route tested (4 flagged nodes at mobile).

None of these scrollable containers have `tabIndex={-1}` (or a `role`/label that makes them
keyboard-operable), so a keyboard-only user cannot scroll them without a mouse/trackpad or
touch gesture once focus is elsewhere on the page. Because this pattern lives in the shared
`Layout.jsx`/`Sidebar.jsx` shell plus the generic table-wrapper class used for wide tables,
it is very likely present on the 8 unaudited routes too, not just the 5 tested here — same
shell, same class names. Fix: add `tabIndex={-1}` (and ideally a `role="region"` +
`aria-label`) to each `overflow-y-auto`/`overflow-x-auto` container that can be the
observable "scrolled" ancestor axe complains about.

### 3. [Serious] Per-row `Checkbox` (16×16px) fails the 44px touch-target minimum — worst on `/observations`

`frontend/src/components/ui/checkbox.jsx` sets the Radix-backed checkbox at a fixed
`h-4 w-4` (16px) with no padding to expand the hit area:

```jsx
className={cn(
  "peer h-4 w-4 shrink-0 rounded-sm border border-primary shadow ...",
  className
)}
```

Radix's `CheckboxPrimitive.Root` renders as a real `<button role="checkbox">`, so this shows
up directly in the touch-target sweep. `/observations` renders one "select all" header
checkbox plus one checkbox per row (2 sample rows in this checkout, from
`AirspaceObservations` count = 2 at `/health`) — all 3 fail at 16px, on **both** viewports
(unlike finding #1, this is not mobile-only). This is a component-level primitive issue, so
any other page/table that uses the shared `Checkbox` inherits the same failure — worth a
sweep of every `Checkbox` call site, not just the one exercised here. Fix: either wrap the
checkbox in a larger clickable label/hit-area (common shadcn pattern: pad the parent `<td>`
or wrap in a 44px `<label>`), or increase the checkbox's own box + touch target via a
utility class override.

### 4. [Design-system gap, not a live-tested violation] The mobile nav "sheet" is hand-rolled, not Radix

`Layout.jsx`'s mobile overlay is three plain `div`s (`fixed inset-0` backdrop + an
absolutely-positioned `Sidebar`) with a backdrop `onClick` to close — no `role="dialog"`,
no `aria-modal="true"`, no focus trap, and no `Escape`-key handler. The repo has a fully
Radix-backed `ui/sheet.jsx` (which provides all of that for free) and even a built-in mobile
variant on `ui/sidebar.jsx`, but neither backs the actual mobile nav. This wasn't caught as
a distinct axe rule in this pass (axe doesn't have a rule that specifically flags "modal
without focus trap"), but it is a real risk: a keyboard user who opens the mobile menu is
not trapped inside it and pressing Escape does nothing, which is exactly the class of
problem a modal-dialog a11y contract exists to prevent. See
`docs/design-system-usage.json` → `controlSourceMap.sheet` for the full comparison against
the unused Radix primitive, and `docs/a11y-evidence/mobile-sheet-nav-open.png` for what it
looks like open.

## Scope limitations

- **5 of 13 reachable routes (~38%), 2 of 13 counting the largest catalog's full 17-page
  set.** This is the smallest-coverage-ratio audit in the family so far, purely because this
  repo has the most pages. Findings #1–#3 above are in shared shell/primitive code and are
  reasoned to generalize to the other 8 untested routes, but that has **not** been verified
  live for each of them — `/aircraft`, `/fr24`, `/routes`, `/infrastructure`, `/airports`,
  `/export`, `/readiness`, and `/spatial-truth` were not run through the harness in this pass.
- **The 4 auth pages** (`/login`, `/register`, `/forgot-password`, `/reset-password`) are
  present in code but redirect to `/` in this `requires_auth: false` diagnostic build, so
  they were not reachable and were skipped, consistent with `docs/GUI_AUDIT.md`.
- **Single theme.** Only the app's one hardcoded dark theme was tested — there is no light
  theme in the CSS to compare against (see Method and `design-system-usage.json`).
- **Sparse sample data.** Per `/health`, this checkout has only 19 airports, 2 synthetic
  observations, 2 export packages, and 4 readiness reports; `AnalysisLenses`,
  `AnalysisObjectives`, `AircraftProfiles`, and all RLSM/FR24/route/infrastructure entities
  are empty. `/analysis` in particular rendered its empty state throughout — a lens-registry
  load failure (likely a `PYTHONPATH`/packaging issue for `skywatcher.core.lenses`, not
  investigated further here) means `AnalysisLenses`/`AnalysisObjectives` report 0 rows even
  though the feature is implemented. Pages with populated tables/drawers/charts under real
  data may surface additional touch-target or contrast issues not visible against empty
  states or the small sample here.
- **axe-core coverage is not exhaustive.** This pass only asserts zero `critical`/`serious`
  violations; `moderate`/`minor` impact violations were not scored or reported, consistent
  with the sibling-repo methodology.
- **No screen-reader pass.** This audit is DOM/axe/keyboard/geometry-based; it does not
  include manual testing with a screen reader (VoiceOver/NVDA/JAWS), so ARIA semantics that
  axe cannot statically evaluate (e.g. whether announced live-region text is actually
  meaningful) were not verified.
