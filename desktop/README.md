# Skywatcher for macOS

Use the standalone macOS `.dmg` from a desktop release:

1. Open the downloaded `.dmg`.
2. Drag **Skywatcher** to **Applications**.
3. Open Skywatcher from Finder or Launchpad.
4. In **Setup & Diagnostics**, choose a workspace and select **Save & Open App**.

The release app is self-contained. End-user setup needs no Terminal and no
separate Python, Node.js, Git, package-manager, or source checkout. Reference
datasets and the built interface are bundled; the selected workspace holds
generated settings, exports, and logs outside the application bundle.

Use the always-available gear button in the app to reopen **Setup & Diagnostics**.
It can choose the workspace, run local checks, or repair generated configuration.
Repair is idempotent and does not delete user data.

## The Launch Pad

`desktop/config.py` declares a **Launch Pad**: a screen the shared desktop
runtime shows after setup and before Skywatcher starts. On it you choose:

- **Guest or Operator.** Guest is read-only: you can browse and query
  everything, and the app refuses archiving snapshots, editing records and
  sky-camera submissions or decisions. Operator allows all of those from this
  computer. Operator can be protected with a passphrase.
- **Open on**: any page from the sidebar.
- **Launch options**: the sky-camera intake rate limit and upload size
  (Operator only), and an optional Anthropic API key for natural-language
  answers in the console. The key is used for that session and never saved;
  with it, questions and matching profile data leave this computer.

It also reports readiness: the airport reference set, how many flight-corpus
snapshots are archived, and how many camera submissions are waiting for review.
Use the **Launch Pad** button beside the gear to come back and change the mode
or options; the app restarts on the page.

Guest mode keeps a shared desktop tidy. It does not stop someone who can already
run programs under your account.

`requirements-desktop.txt` pins a `prii-desktop` that includes the Launch Pad
(0.3.0). If you set the app up before that pin moved, run
`python desktop/setup.py --force` once to install the newer runtime.

The Launch Pad is registered as `desktop-launch-pad` in
`.federation/gui-capabilities.json`. Its end-to-end test,
`frontend/tests/desktop-launchpad.spec.mjs`, opens the runtime's real page in a
browser and drives the real bridge and backend through
`frontend/tests/support/launchpad_harness.py`; only the native window is
replaced. It checks the readiness rows and start pages; that Guest may still
use the two read-only POSTs (`/api/query`, `/api/entities/*/filter`) but is
refused a write; that Operator's write gets through; and that an Operator
option reaches the backend's environment. To run it, with
`server/backend/requirements.txt` and `requirements-desktop.txt` installed:

```bash
cd frontend && npm run test:desktop-launchpad
```

It runs in CI in the GUI Reachability E2E job. One known runtime defect is
asserted rather than hidden: in Guest, the pinned runtime dims Operator-only
options below the WCAG contrast minimum (fixed in the hub, thehub-pr#435); the
test fails if any other accessibility violation appears.

Map tiles still require a network connection; local data, tables, and charts
continue to work when those tiles are unavailable.

## If macOS blocks the first open

Open **System Settings → Privacy & Security**, find the message naming
Skywatcher, and select **Open Anyway**. This is the complete UI-only recovery
path for an unnotarized development release.

## Architecture

`desktop/config.py` is the thin Skywatcher adapter. Native first-run setup,
repair, diagnostics, the per-user lock, same-origin serving, and the pywebview
window live in `thehub-pr/packages/prii_desktop`. Release CI builds and smokes
the frozen app on macOS, Windows, and Linux and packages the macOS `.dmg`.

`desktop/setup.py` and command-line launcher flags remain developer conveniences;
they are not part of end-user installation.
