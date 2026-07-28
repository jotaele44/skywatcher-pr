# Skywatcher desktop

## Install on macOS — no Terminal

1. Open this repository's **Releases** page and download the latest
   `PRII-SKYWATCHER-macOS.dmg`.
2. Open the disk image and drag **Skywatcher** to **Applications**.
3. Open Skywatcher from Applications.

The release contains its own Python runtime, backend, compiled interface, and
committed airspace/reference resources. Python, Node.js, Git, Homebrew, and
Terminal are not required.

On first launch, the native **Setup & Repair** screen asks for a writable data
location, verifies packaged resources and private loopback networking, and
starts the app. **Setup & Diagnostics** remains available in the lower-right
corner for repair. The current review overlay is session-scoped and the
committed source artifacts remain read-only.

Map basemap tiles may require an internet connection; the packaged tables,
charts, evidence, and synthetic/reference data remain available offline.

## If macOS blocks the first open

Open **System Settings → Privacy & Security**, find the message naming
Skywatcher, and choose **Open Anyway**. No quarantine command is required.
Release CI applies an ad-hoc integrity signature, but public downloads are not
Apple-notarized unless a release is signed with project Developer ID
credentials.

The `PRII-SKYWATCHER.app` committed in a source checkout is a Finder-only
download helper. The self-contained product is the app inside the release disk
image.

## Release contract

The `desktop-build` workflow builds on clean Linux, macOS, and Windows runners,
then tests the fresh-machine setup contract and backend health on the frozen
executable. macOS CI verifies the bundle signature before producing the `.dmg`.

`desktop/launch.py` and `desktop/config.py` are thin adapters over TheHub's
shared `prii_desktop` runtime. Source-checkout setup scripts remain developer
conveniences and are not part of end-user installation.
