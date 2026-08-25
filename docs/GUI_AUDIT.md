# GUI Audit — Skywatcher-PR

Audit date: 2026-08-23
Scope: `frontend/` (React/Vite SPA), plus the desktop launcher entry points at the repo root.

## Overview

**What this app is.** Skywatcher-PR is the airspace/aircraft-intelligence node of the PRII
federation (`programId: skywatcher-pr`, `federationRole: airspace_intelligence_node`,
parent hub `thehub-pr`). It is a **read-only diagnostic dashboard** over Puerto Rico
airspace observations derived from FR24 screenshots/tracks: aircraft profiles, route-line
mining, airspace↔infrastructure proximity links, a manual-review queue, a federation
export/validation center, a SATIM visual-artifact calibration report, and an
"Aircraft Spatial Truth" (RLSM) georeferencing report. The whole app ships stamped
`NON_PRODUCTION_DIAGNOSTIC` — every page carries a diagnostic-notice banner, and the UI is
explicitly a **visualization & validation surface**: real ingestion, scraping, OCR and
federation export execution all happen repository-side (Python scripts / cron), never from
the browser.

**Tech stack.** React 18 + Vite 5, `react-router-dom` v6, Tailwind CSS, shadcn/ui component
primitives (Radix UI underneath most, but the toast primitives — see Findings — are plain
`div`s, not Radix), `@tanstack/react-query` (present but lightly used — most data comes from
a custom `SkywatcherDataProvider`/`federationClient` fetch layer, not React Query), Recharts
for the two charts, `lucide-react` icons. 117 `.jsx`/`.tsx` files under `frontend/src`, of
which 16 are top-level pages (`frontend/src/pages`, one `.test.jsx` excluded) and 7 are the
shared slide-in "detail drawers" (`frontend/src/components/skywatcher/drawers`).

**Backend used for this audit.** `server/backend/main.py` is a small read-only FastAPI
server that serves entity data straight from repository artifacts — the airport registry
(`data/reference/pr_airports.jsonl`), the bundled synthetic export package
(`exports/examples/synthetic_airspace_package/observations.csv`), federation evidence
(`reports/federation/evidence_skywatcher-pr.jsonl`), and (if present locally) an RLSM
SQLite corpus for spatial-truth data. It needs **no external API keys** and was used as-is
for live verification. In this checkout the RLSM SQLite DB, FR24 captures, route segments,
infrastructure assets, aircraft profiles, asset links, manual-review items and federation
sync events are all **empty** (`/health` reported 0 rows for each) — only 19 airports, 2
synthetic observations, 2 export packages and 4 readiness reports are populated. That
constrained how much end-to-end interaction (drawers with real linked records, kanban cards,
capture actions) could be exercised live; those gaps are called out per-page below.

**Entry points.**
- Dev URL: `npm run dev` (Vite, default port `5173`; this audit ran it on `5193` with
  `VITE_API_PROXY_TARGET` pointed at the FastAPI server on `8017`, both non-default to avoid
  colliding with sibling repos' dev servers in this shared container).
- Desktop launcher: `PRII-SKYWATCHER.command` (macOS)/`.sh` (Linux)/`.bat` (Windows), or the
  `PRII-SKYWATCHER.app` bundle — see **Desktop Launcher** section below.
- Production/desktop serving: the FastAPI backend also serves the built SPA same-origin
  (`desktop/app_server.py`), so there is no separate "prod URL" — one process serves both.

**Auth posture at runtime.** `GET /api/apps/public-settings` reports `requires_auth: false`
in this diagnostic backend, so `App.jsx` redirects `/login`, `/register`,
`/forgot-password` and `/reset-password` straight to `/` (verified live). Those four pages
are fully implemented but **unreachable** unless a backend is configured with
`requires_auth: true` and real `/auth/*` endpoints — they are catalogued below and marked
static-only.

---

## Shared / Global Components

These render on every route (via `Layout`/`App`) or are reused across many pages. Listed
once here; page sections below reference them rather than repeating their internals.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Sidebar nav — 12 links | Link (`react-router-dom`) | Command Dashboard, Airspace Observations, Aircraft Profiles, FR24 Intake, Aircraft Spatial Truth, Route-Line Mining, Infrastructure Links, PR Airports, Manual Review, Federation Export, Readiness / Blockers, SATIM Calibration | `<Link to="...">`, client-side route change; active state via `pathname.startsWith` | Live | `frontend/src/components/skywatcher/Sidebar.jsx`. All 12 targets confirmed to load (0 console errors each) |
| Mobile menu toggle | Button (icon) | Menu / X (Lucide) | `setMobileOpen(v => !v)` — shows/hides the mobile sidebar overlay | Live | `Layout.jsx`; verified open→link click→auto-close |
| Mobile sidebar backdrop | Click target (div) | — | `onClick={() => setMobileOpen(false)}` closes the overlay | Static | Same file, trivial — not separately re-tested |
| Toast close (X) button | Button (icon) | — (X icon) | **No `onClick` handler at all** — see Findings | Live — **BROKEN** | `components/ui/toast.jsx` `ToastClose`; reproduced: click does nothing, toast stays on screen |
| Error boundary "Reload" | Button | Reload | `window.location.reload()` | Static | `components/ErrorBoundary.jsx`, only renders after an uncaught render error |
| 404 "Go Home" | Button | Go Home | `window.location.href = '/'` | Static | `lib/PageNotFound.jsx`; also fires a `federation.auth.me()` React Query call to conditionally show an "Admin Note" |
| Detail drawer close (×3 ways) | Button / click-target / keyboard | X icon, backdrop click, Esc key | `onClose()` → pops the drawer stack in `DrawerHub` | Live | `SideDrawer.jsx`; verified via Escape key on the Observation drawer |

**Detail Drawers** (`components/skywatcher/drawers/*`, opened via `useDrawers().open.*` from
row/card clicks across pages; stacked, so opening a linked record pushes a new drawer over
the last one, and `go.*` swaps the top slot instead of stacking further):

| Drawer | Internal controls | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|
| **ObservationDetailDrawer** | `ReviewActions`: Triage / Needs Review / Verify / Reject buttons | `onChange(status)` → `d.updateRecord("observations", id, {review_status})` → `PATCH /api/entities/AirspaceObservations/{id}` | Live | Clicked "Verify" on a real sample observation — no error, optimistic UI update applied |
| | LinkChip → Linked Aircraft Profile | `go.aircraft(id)` — swaps drawer to `AircraftDetailDrawer` | Static | 0 aircraft profiles in this checkout's sample data |
| | LinkChip → Linked FR24 Capture | `go.capture(id)` | Static | 0 captures in sample data |
| | RouteSegmentPanel → Linked Route Segments (N) | `go.route(id)` per segment | Static | 0 routes in sample data |
| | InfrastructureLinkPanel → Infrastructure Links (N) | `go.asset(id)` per link | Static | 0 links in sample data |
| **AircraftDetailDrawer** | LinkChip → Observation History (N) | `go.observation(id)` | Static | requires aircraft data |
| | RouteSegmentPanel → Linked Routes (N) | `go.route(id)` | Static | requires aircraft data |
| **CaptureDetailDrawer** | Footer: Queue Capture | `placeholder()` → toast only, "diagnostic placeholder, no execution" | Static | requires FR24 capture data |
| | Footer: Open Manual Review | `d.createReview({...})` → `POST /api/entities/ManualReviewItems` + toast | Static | " |
| | Footer: Link Observation | `placeholder()` → toast only | Static | " |
| | Footer: Mark Duplicate | `setStatus("duplicate")` → `PATCH .../captures/{id}` + toast | Static | " |
| | Footer: Reject Capture | `setStatus("rejected")` → `PATCH .../captures/{id}` + toast | Static | " |
| | sha256 Copy button | `navigator.clipboard.writeText(hash)` + toast "Hash copied" | Static | " |
| | LinkChip / RouteSegmentPanel cross-nav | `go.observation` / `go.route` | Static | " |
| **RouteDetailDrawer** | `ReviewActions` (4 buttons, same set as Observation) | `PATCH .../routes/{id}` | Static | requires route data |
| | LinkChip → Capture, → Observation | `go.capture` / `go.observation` | Static | " |
| **AssetDetailDrawer** | InfrastructureLinkPanel → Spatial Relationship Links | `go.observation(link.observation_id)` | Static | requires infrastructure asset data |
| | LinkChip → Linked Observations | `go.observation(id)` | Static | " |
| **ExportDetailDrawer** | (read-only; no action buttons) | — | Live | Opened via ExportCenter "Details →"; renders `ExportValidationPanel` and blocker explanation, both real sample packages |
| **ReviewDetailDrawer** | `ReviewActions`: Start Review / Resolve / Reject | `setStatus(s)` → `PATCH .../reviews/{id}` (+ `resolved_at` stamp on resolve/reject) | Static | 0 review items in sample data |
| | Notes `<textarea>` + "Save Notes" button | `d.updateRecord("reviews", id, {notes})` + toast | Static | " |
| | LinkChip → underlying linked record | `openTarget()` → routes to observation/capture/route/aircraft/export drawer by `item_type` | Static | " |

---

## Dashboard (`/`, `pages/Dashboard.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Recent Observations row | Table row (click) | callsign row | `open.observation(o.observation_id)` → opens ObservationDetailDrawer | Live | 2 sample rows clicked through successfully |
| Manual Review Items panel item | Click target (`ManualReviewPanel`) | review reason text | `open.review(r.review_id)` → opens ReviewDetailDrawer | Static | 0 open review items in sample data |
| Map markers (observation / airport / asset) | SVG hover | — | `onMouseEnter/onMouseLeave` → shows a floating tooltip; **not clickable** | Live | `PuertoRicoMapShell.jsx`. Confirmed no navigation on click — hover-only by design |
| Heat-map municipality bubble | SVG hover | — | Same hover-tooltip pattern | Static | `ObservationHeatMap.jsx` |
| Hourly Observations bar chart | Recharts `<Bar>` hover | — | Recharts built-in tooltip on hover | Static | `HourlyObservationsChart.jsx` |
| Federation Sync Events table | Static table | — | No row click handler — display only | Live | Confirmed non-interactive (unlike every other list/table page) |

Recent Observations and the Federation Sync Events table both render every field from
whatever the `/api/entities/*` backend returns; with this repo's bundled sample backend, the
synthetic-package-sourced rows are missing several fields the UI expects — see **Findings**.

## Airspace Observations (`/observations`, `pages/Observations.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search callsign, tail, operator, airport, asset…" | Client-side substring filter over 6 fields | Live | Typed "N" — filtered to 0/2 rows correctly (neither sample row matches) |
| Review status filter | `<select>` | "All review states" / New / Triaged / Needs Review / Verified / Rejected | Client-side filter on `review_status` | Live | Cycled through option 1 ("New") — row count updated correctly |
| Source type filter | `<select>` | "All sources" / Synthetic Example / FR24 Screenshot / FR24 Track / Manual Entry / Registry Match | Client-side filter on `source_type` | Live | " |
| Synthetic flag filter | `<select>` | "Synthetic & live" / Synthetic only / Live only | Client-side filter on `synthetic_flag` | Live | " |
| Confidence filter | `<select>` | "All confidence" / High / Medium / Low | Client-side filter on `confidence_score` bands | Live | " |
| Sort | `<select>` | Newest / Confidence / Distance to asset | Client-side sort | Live | " |
| Select-all checkbox | Checkbox (header) | — | Toggles all filtered row IDs into/out of `selected` Set | Live | |
| Per-row checkbox | Checkbox | — | Toggles one row ID; `stopPropagation` so it doesn't also open the drawer | Live | |
| Bulk "Approve" | Button | Approve | Loops `updateRecord("observations", id, {review_status:"verified"})` per selected row, then toasts | Live | Clicked with 1 row selected — no console error, toast confirmed |
| Bulk "Flag for review" | Button | Flag for review | Same pattern, sets `needs_review` | Static | Code-identical to Approve path; not separately re-clicked |
| Bulk "Clear" | Button | Clear | `setSelected(new Set())` | Static | Trivial local state reset |
| Table row | Row click | — | `open.observation(o.observation_id)` → ObservationDetailDrawer | Live | See drawer table above |
| Map (filtered observations) | Same `PuertoRicoMapShell` as Dashboard | — | Hover tooltips only | Static | Not re-verified per-page |

## Aircraft Profiles (`/aircraft`, `pages/Aircraft.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search callsign or tail number…" | Client-side filter | Static | 0 aircraft in sample data — filter logic read from source, not exercised against real rows |
| Operator category filter | `<select>` | dynamic, built from `d.aircraft` | Client-side filter | Static | " |
| View toggle — Cards | Button | Cards | `setView("cards")` | Live | Toggled between both states with no error; page correctly rendered the `EmptyState` ("No aircraft profiles") in both modes since 0 rows exist here |
| View toggle — Table | Button | Table | `setView("table")` | Live | " |
| Aircraft card (cards view) | Click target | — | `open.aircraft(a.aircraft_id)` | Static | requires aircraft rows |
| Table row (table view) | Row click | — | `open.aircraft(a.aircraft_id)` | Static | " |

## FR24 Intake (`/fr24`, `pages/FR24Intake.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search file name, capture id, hash…" | Client-side filter | Static | 0 captures in sample data |
| Ingest status filter | `<select>` | All / Queued / Processed / Needs Manual Review / Duplicate / Corrupt / Rejected | Client-side filter | Static | " |
| Table row | Row click | — | `open.capture(c.capture_id)` → CaptureDetailDrawer | Static | " |

Page also carries a static "repository-side" info banner (no control) reiterating that no
scraping/OCR/ingestion runs from the browser.

## Aircraft Spatial Truth (`/spatial-truth`, `pages/SpatialTruth.jsx`)

Fully read-only — **zero interactive elements** beyond the shared map. Renders RLSM
marker/georeference accounting metrics, a bounded-position map, and three data tables
(located aircraft, frame accounting, zoom ladder). No row clicks, no filters, no drawers.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Map (`PuertoRicoMapShell`, `diagnostic=false`) | Hover only | — | Tooltip on hover | Live | Page loaded with 0 console errors; RLSM tables empty (no local SQLite corpus in this checkout) |

## Route-Line Mining (`/routes`, `pages/Routes.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search route name, cluster, method…" | Client-side filter | Static | 0 route segments in sample data |
| Review status filter | `<select>` | same 5-state set as Observations | Client-side filter | Static | " |
| Route cluster cards | Static (display only) | — | No click handler | Live | Confirmed non-interactive |
| Table row | Row click | — | `open.route(r.route_segment_id)` → RouteDetailDrawer | Static | requires route data |
| Map (routes) | Hover only | — | Tooltip | Static | shared component |

## Infrastructure Links (`/infrastructure`, `pages/Infrastructure.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search asset, municipality…" | Client-side filter | Live | Empty-state path confirmed (0 assets) |
| Asset type filter | `<select>` | dynamic | Client-side filter | Live | 3 selects confirmed present |
| Municipality filter | `<select>` | dynamic | Client-side filter | Static | " |
| Proximity radius filter | `<select>` | Any / 5 / 10 / 25 / 50 nm | Client-side filter, also filters each asset's link list | Static | " |
| Asset card header | Click target (button) | asset name | `open.asset(a.asset_id)` → AssetDetailDrawer | Static | requires asset data |
| InfrastructureLinkPanel "Open" | Button (per link, ≤3 shown) | — | `open.observation(l.observation_id)` | Static | " |

## PR Airports (`/airports`, `pages/Airports.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search box | Text input | "Search airport, FAA, ICAO, municipality…" | Client-side filter over 4 fields | Live | Typed "San Juan" — 19 rows → 1 row, correct |
| Linked-aircraft chip (per row, ≤3) | Button | tail number | `open.aircraft(ac.aircraft_id)` → AircraftDetailDrawer | Static | requires aircraft data |
| Map (airports) | Hover only | — | Tooltip | Static | shared component |

**Note:** unlike every other list page in this app, the Airports table **rows themselves
are not clickable** — there is no per-airport detail drawer, only the nested
linked-aircraft chips. This is a design choice (airports have no dedicated drawer in
`DrawerHub`), not a broken control, but it is inconsistent with the row-click pattern used
on Observations/Aircraft/FR24/Routes and worth a UX pass if that inconsistency wasn't
intentional.

## Manual Review Queue (`/review`, `pages/ManualReview.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Kanban card (Open / In Review / Resolved / Rejected columns) | Click target (`ManualReviewPanel`) | — | `open.review(r.review_id)` → ReviewDetailDrawer | Static | 0 review items in sample data; all 4 empty-state columns rendered correctly (4 `<h3>` column headers confirmed live) |

Purely a 4-column kanban read layout — no drag-and-drop, no column-level actions, no bulk
actions on this page (bulk actions only exist on the Observations page).

## Federation Export Center (`/export`, `pages/ExportCenter.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Details →" (per export package) | Button | Details → | `open.export(pkg.package_id)` → ExportDetailDrawer | Live | Opened successfully against a real sample package, closed via Escape |
| Command Reference "Copy" (×6, one per `REPO_COMMANDS` entry) | Button | Copy → Copied | `navigator.clipboard.writeText(command)`; `setCopied(true)` for 1.5s | Live | Confirmed functional via direct DOM `click()` — button flips "Copy"→"Copied" within one animation frame. (Playwright's synthetic `locator.click()` had an unrelated timing quirk against this element that made it *look* inert; a raw DOM click proved the handler fires correctly, so this is **not** a bug — see Findings for the one that is) |

Both export packages in the sample data are `test` mode, so the hard production-block rule
(`production` + `contains_synthetic_rows` ⇒ blocked) is described but not exercisable live
here — would need a `production`-mode package to trigger the blocked-state UI branch.

## Readiness / Blockers (`/readiness`, `pages/Readiness.jsx`)

**Zero interactive elements.** Pure read-only status page: 11 static readiness cards, an
active-blockers/warnings panel, and a numbered "recommended next actions" list. No
buttons, links, filters, or clickable rows anywhere on this page.

## SATIM Calibration (`/calibration`, `pages/Calibration.jsx`)

**Zero interactive elements.** Fetches a committed static JSON artifact
(`frontend/public/satim/moca_fr24_2025.summary.json`, generated by
`scripts/satim_score_labels.py --frontend-out`) on mount and renders it as metric cards,
score bars, a promotion-gate panel, and three read-only tables (candidates, marker legend,
marked features). No row clicks, no filters.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| (fetch on mount) | — | — | `fetch(SUMMARY_URL)` on `useEffect` | Live | Confirmed the bundled JSON loads with 0 console errors and the page renders its full content (not the "no calibration summary" empty-state branch) |

---

## Login (`/login`, `pages/Login.jsx`)

Static-only in this checkout: `requires_auth: false` in the sample backend means `/login`
redirects to `/` before render (verified live — `page.goto('/login')` resolved to `/` with
the Dashboard heading). Cataloguing what the code implements:

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Continue with Google" | Button | Continue with Google | `federation.auth.loginWithProvider("google", "/")` → full-page redirect to `{apiBase}/auth/google/login` | Static-only: requires a backend with `/auth/google/login` + real Google OAuth app | |
| Email field | Text input | Email | Controlled input, `required`, `type=email` | Static-only: requires `requires_auth:true` backend | |
| Password field | Password input | Password | Controlled input, `required` | Static-only | |
| "Forgot password?" | Link | Forgot password? | Routes to `/forgot-password` | Static-only | |
| Submit | Button | Log in → "Logging in…" | `federation.auth.loginViaEmailPassword(email, password)` → `POST /auth/login`; on success, `window.location.href = "/"` | Static-only: requires `/auth/login` endpoint | |
| "Create one" | Link | Create one | Routes to `/register` | Static-only | |

## Register (`/register`, `pages/Register.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| "Continue with Google" | Button | Continue with Google | same as Login | Static-only | |
| Email / Password / Confirm Password fields | Text/password inputs | — | Controlled; client-side password-match check before submit | Static-only | |
| Submit | Button | Create account → "Creating account…" | `federation.auth.register({email,password})` → `POST /auth/register`, then shows OTP step | Static-only: requires `/auth/register` | |
| OTP input (6 slots) | `InputOTP` | — | `value`/`onChange` bound to `otpCode` state | Static-only | |
| "Verify" | Button | Verify → "Verifying…" | `federation.auth.verifyOtp({email, otpCode})` → `POST /auth/verify-otp`; stores token, redirects to `/` | Static-only: requires `/auth/verify-otp` | |
| "Resend" | Button (text-style) | Resend | `federation.auth.resendOtp(email)` → `POST /auth/resend-otp` + toast "Code sent" | Static-only: requires `/auth/resend-otp` + email delivery | |
| "Log in" | Link | Log in | Routes to `/login` | Static-only | |

## Forgot Password (`/forgot-password`, `pages/ForgotPassword.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Email field | Text input | Email address | Controlled | Static-only | |
| Submit | Button | Send reset link → "Sending…" | `federation.auth.resetPasswordRequest(email)`; **always** shows the "check your email" success state, even on error (deliberate — avoids account enumeration) | Static-only: requires `/auth/password/reset-request` | |
| "Back to log in" | Link | Back to log in | Routes to `/login` | Static-only | |

## Reset Password (`/reset-password`, `pages/ResetPassword.jsx`)

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| New Password / Confirm Password fields | Password inputs | — | Controlled; client-side match check | Static-only | Only rendered when a `?token=` query param is present |
| Submit | Button | Reset password → "Resetting…" | `federation.auth.resetPassword({resetToken, newPassword})` → `POST /auth/password/reset`; redirects to `/login` on success | Static-only: requires `/auth/password/reset` | |
| "Request a new link" | Link | Request a new link | Shown instead of the form when no `?token=` is present; routes to `/forgot-password` | Static-only | |

---

## Desktop Launcher

Four launcher entry points, all converging on the same two-step flow:

1. **`desktop/setup.py --ensure`** (idempotent, skipped after first successful run via a
   `.setup-complete` marker): creates a private `.venv` under the repo root, installs
   `server/backend/requirements.txt` plus `desktop/config.py`'s `EXTRA_PIP_SPECS`
   (pywebview, prii-desktop) into it (needs internet the first time only), then runs
   `npm ci && npm run build` in `frontend/` to produce
   `frontend/dist/` — with `VITE_SKYWATCHER_API_BASE_URL`/`VITE_FEDERATION_API_BASE_URL`
   forced blank at build time so the desktop build can't be pointed at an external backend.
2. **`desktop/launch.py`** (via `.venv/bin/python`): thin shim that calls
   `prii_desktop.launch(DesktopConfig.from_module(desktop.config))` — a shared launcher
   runtime vendored from the sibling `thehub-pr` repo. It starts `uvicorn` serving
   `server.backend.main:app` (same FastAPI app used for dev/this audit) **plus** the built
   SPA same-origin (`desktop/app_server.py` → `make_desktop_app`), waits on the `/health`
   endpoint, takes a single-instance lock, then opens a native `pywebview` window pointed at
   that local server (title "Skywatcher", from `desktop/config.py`). Flags: `--no-window`
   (headless server only), `--browser` (open default browser instead of a native window),
   `--route PATH` (open to a specific route), `--smoke` (CI smoke-test mode).

Platform entry points, all self-locating (`cd` to the repo root first) and all delegating to
the two steps above:

| Launcher | Platform | Behavior |
|---|---|---|
| `PRII-SKYWATCHER.command` | macOS (double-click) | Finds `python3`, runs setup, `exec`s `launch.py` |
| `PRII-SKYWATCHER.sh` | Linux | Same, via `/bin/sh` |
| `PRII-SKYWATCHER.bat` | Windows | Same, via `py -3`/`python`, pauses the console on error |
| `PRII-SKYWATCHER.app/Contents/MacOS/PRII-SKYWATCHER` | macOS `.app` bundle | Same, plus restores `PATH` (Finder-launched `.app`s lack Homebrew/python.org paths) and shows native `osascript` dialogs on failure instead of console output |
| `Fix-Gatekeeper.command` | macOS | Separate helper — clears the quarantine flag so an unsigned `.app` opens without a Gatekeeper block |

`desktop/README.md` notes the packaged end-user path is actually a signed `.dmg` release
(built by CI) with a first-run "Setup & Diagnostics" screen for choosing a workspace — the
launcher scripts above and `desktop/setup.py` are developer conveniences, not what a real
end user installs. This audit did not attempt to run the actual desktop window (no display
in this container); the FastAPI backend it wraps was exercised directly (see per-page tables
above) since `APP_IMPORT = "server.backend.main:app"` is exactly the server this audit ran
on port 8017.

---

## Findings

1. **Toast close button is dead (confirmed, reproducible).**
   `components/ui/toast.jsx`'s `ToastClose` renders a `<button>` with the styling hook
   `toast-close=""` but **no `onClick` handler at all**. Triggered a toast (Observations →
   select a row → Approve), then clicked its close (×) button twice via Playwright — the
   toast count stayed at 1 both times; it does not dismiss. Toasts otherwise auto-expire
   after `TOAST_REMOVE_DELAY = 1_000_000`ms (≈16.7 minutes), so in practice a user has no way
   to dismiss a toast early. Root cause: this toast implementation is plain `div`s, not
   wired to `@radix-ui/react-toast` (which the app depends on but doesn't use here), so
   `ToastClose` never got a dismiss handler wired up the way a Radix `Toast.Close` would
   provide automatically.

2. **Console warning on every toast.** `toaster.jsx` spreads `{...props}` — including a
   Radix-style `onOpenChange` callback set by `use-toast.jsx` — onto `Toast`, which is a
   plain `<div {...props}>`. React logs `Warning: Unknown event handler property
   \`onOpenChange\`. It will be ignored.` in the console every single time any toast fires
   (bulk actions, capture actions, review notes, OTP resend, hash copy, etc.). Harmless
   functionally but a real, reproducible console error — same root cause as #1.

3. **Sample-backend/frontend field-shape mismatch on Observations.** The bundled
   `server/backend/main.py` aliases some fields from the synthetic CSV package
   (`synthetic_flag`, `confidence_score`, `created_date`, `observed_at`, `latitude`,
   `longitude`) but not others the UI reads directly: `callsign`, `tail_number`,
   `aircraft_type`, `operator_name`, `mission_inference`, `nearest_airport_name`,
   `nearest_asset_name`, `distance_nm`, and `source_type` (CSV has `"screenshot"`, the UI's
   `SOURCE_OPTS`/`SourceProvenanceBadge` expect e.g. `"fr24_screenshot"`). Live effect:
   both sample rows on `/observations` (and Dashboard's "Recent Observations") render with a
   blank Callsign/Tail cell, blank Mission badge, blank Nearest-Asset cell, and opening
   either row's `ObservationDetailDrawer` shows an **empty drawer title** (bound to
   `obs.callsign`, which is `undefined`) and blank Tail/Operator/Mission/Nearest-Airport
   fields inside. This is specific to this bundled sample dataset/backend pairing — the row
   click, drawer open/close, and review-status buttons all work correctly — but it's a real
   content gap surfaced by live testing, not a hypothetical one. Worth either extending the
   backend's `load_observations()` aliasing or updating the synthetic CSV schema.

4. **Airports page rows aren't clickable, unlike every other list page.** Not a bug — there
   is no `AirportDetailDrawer` in `DrawerHub` for it to open — but every other primary list
   (Observations, Aircraft, FR24 Intake, Routes) opens a detail drawer on row click, and
   Airports silently doesn't, with only the nested aircraft chips being clickable. Flagged as
   a UX inconsistency in case it wasn't deliberate.

5. **`ProtectedRoute.jsx` and `UserNotRegisteredError.jsx` are dead code.** Both exist under
   `frontend/src/components/` but are never imported by `App.jsx` — routing has no
   authentication gate at the route level (auth-required pages are excluded from the route
   table entirely instead, per the comment in `App.jsx`). Not a bug in the live app (nothing
   references them), just unused scaffolding worth a note.

6. **Map markers are hover-only, everywhere.** All three uses of `PuertoRicoMapShell`
   (Dashboard, Observations, Routes, Airports, SpatialTruth) and `ObservationHeatMap`
   (Dashboard) show a tooltip on hover but never navigate anywhere on click, even though the
   hovered data (`hover.data`) is exactly the record a detail drawer could open. Confirmed
   by reading every marker's event handlers — only `onMouseEnter`/`onMouseLeave` are wired,
   no `onClick`. Consistent everywhere, so likely deliberate, but worth flagging since it's
   the one place in the app where a piece of on-screen data *looks* interactive (cursor:
   pointer, tooltip) but has no click behavior.

No other broken/dead controls were found. Every button, select, checkbox, and row-click
handler that had representative sample data behaved as its source code says it should, with
zero console/page errors across all 12 non-auth routes and the interaction sequences run
against Observations, Aircraft, Export Center, Manual Review, Infrastructure, Routes, and
Airports.

---

## Summary

- **Pages catalogued:** 16 top-level pages under `frontend/src/pages` (12 reachable in this
  diagnostic-mode build; 4 auth pages present in code but redirect-gated to unreachable).
- **Interactive elements catalogued:** **≈119 distinct control definitions** — counting each
  distinct interactive element *type* once (a filter `<select>`, a table row's click
  handler, a drawer's close button), not each runtime repetition of a templated row/card
  across however many data rows happen to be loaded. Breakdown: 17 global/shared chrome
  elements (nav, mobile menu, toasts, error/404 recovery) + 38 across the 7 shared detail
  drawers + ~64 spread across the 12 dashboard-style pages + 22 across the 4 auth pages.
- **Live-verified vs. static-only:** roughly **45 elements exercised live** in a running
  Chromium session against the bundled read-only FastAPI backend (all filters/selects/search
  on Observations, Infrastructure, Airports; bulk-select + Approve on Observations; view
  toggle on Aircraft; row-click → drawer open/close/Escape and one `ReviewActions` click on
  Observations; "Details →" drawer + command-reference Copy on Export Center; mobile nav
  toggle + link click; all 12 non-auth routes loading with zero console errors). The
  remaining **~74 elements are static-only** — either because this checkout's sample backend
  has zero rows for that entity (aircraft, FR24 captures, routes, infrastructure assets,
  review items, RLSM spatial data — all confirmed 0 via `/health`), or because they need real
  external services this audit was explicitly told not to chase (Google OAuth, `/auth/*`
  email/OTP endpoints, live FR24/ADS-B ingestion).
- **Broken/dead controls found:** **1 confirmed** — the toast notification's close (×)
  button has no click handler and does not dismiss the toast (Finding #1), paired with a
  reproducible React console warning on every toast (Finding #2). Everything else that could
  be exercised against real sample data worked as coded; the remaining findings (#3–#6) are
  content/consistency observations, not broken controls.
