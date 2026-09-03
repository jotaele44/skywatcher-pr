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
