# Access and recovery correction — 2026-09-08

Full program status: OPEN. This is continued implementation toward the original completion objective, not a new completion boundary.

## Corrected behavior

Public settings no longer convert network failures into an assumed anonymous configuration. The client requires the existing backend envelope with a boolean `public_settings.requires_auth`; missing/malformed policy is an error. Startup waits for settings and account verification, exposes a visible retry on failure, and preserves the requested page. Authentication pages do not mount the protected data provider. A backend-required account check runs even when no bearer token is stored, supporting authenticated cookie sessions.

After sign-in, valid local destinations are retained. External, malformed, authentication-loop, and double-slash path destinations fall back home. Validated destinations retain their absolute same-origin URL to prevent path reinterpretation. This changes client routing only; API authorization remains the server's responsibility. The diagnostic backend still does not implement an account provider, and mocked authentication tests do not certify production authentication services.

Clear-access-token and clear-write-token URL flags are consumed once and stripped from the URL. Legacy persisted flags are discarded. Replacement credentials survive subsequent reloads.

Failed password-reset requests retain the address and offer neutral retry without implying email delivery or revealing account existence. Clipboard controls await the browser's write result, expose failure/manual-copy guidance, and confirm only successful writes. Clipboard behavior is explicitly `client_only` in the capability manifest and does not execute a repository command.

## Verification and scope

The validation receipts are in `/Users/jotaele/fed-repos/_skywatcher_access_recovery_20260908`:

- `unit-final.log`: configured frontend unit suite, 77 tests.
- `browser-terminal.log`: recovery/authentication/token/mobile regression suite, including positive and negative redirect cases.
- `routes.log`: all 14 visible routes plus manifest gate (15 tests).
- `terminal-gate-exits.json`: configured typecheck, lint and production-build exits.
- `gui-parity-terminal.json` and `parity-tests.log`: final manifest validation and parity checker regressions.
- `route-set-equivalence.json`: clipboard classification leaves the route test set unchanged: intersection/union 14, both one-sided differences and symmetric difference empty.

Failed attempts are retained: an incorrect login email locator, and a five-second post-navigation render deadline that expired just before the expected dashboard appeared. The corrected test retains visibility and destination assertions with a bounded fifteen-second navigation/render allowance. Terminal receipts supersede those attempts; they are not erased or counted as passes.

Existing backend implementation files are unchanged. Earlier Python and export evidence remains bounded to those unchanged files; this frontend correction does not establish new live-source readiness.

## Completion denominator

All 1,885 original discovery findings remain in `completion-inventory-adjudicated.json`. The clipboard control has direct local runtime/unit proof and is marked PASS within its explicit client-only scope. Arithmetic: 1,885 original = 1 PASS + 1,884 OPEN + 0 excluded. The scanner's 1,873 legacy findings reflect additional mappings, not twelve fully completed user workflows. Authentication-provider completion remains OPEN.

The PR queue, two issues, source/identity requirements, imagery migration, device proof, and unresolved shared-contract comparisons remain in the full-program scope. No shared schema or other canonical repository was changed. No universal saturation, percentage completion or CERTIFIED label is asserted.

## Next concrete corrections

First, test the API destination override with synthetic credentials: `api_base_url` can override the configured endpoint while the request client attaches stored credentials. This observed code path remains OPEN for controlled cross-origin reproduction and destination-policy enforcement; it is recorded in `next-security-review.json`. No real credentials should be sent to an external test host.

`frontend/src/pages/Readiness.jsx` renders hardcoded runtime claims from `READINESS_ITEMS` independently of the fetched report, including discovery readiness, package presence, missing live observations, and test-mode-only adapter operation. Replace these with authoritative report fields or explicit unknown states, and test both positive and negative inputs. The evidence and source hash are retained in `next-action-evidence.json`. This newly identified defect remains OPEN in addition to the original inventory.
