# macOS release security

Skywatcher distributions should be code-signed and notarized. The repository does not ship a command that removes quarantine attributes or bypasses Gatekeeper.

For development builds, run from a trusted local checkout and follow Apple's standard per-application approval flow. Do not distribute generalized `xattr`, `spctl`, or trust-bypass scripts.
