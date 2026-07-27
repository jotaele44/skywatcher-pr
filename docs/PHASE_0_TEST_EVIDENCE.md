# Phase 0 Test Evidence

Environment: isolated Linux workspace, Python 3.13.5. The supplied archive intentionally omitted `frontend/` and production `data/`.

| Gate | Result |
|---|---|
| Core collection without production data or sibling checkout | PASS |
| Default core suite | 754 passed, 36 skipped, 53 deselected |
| Minimum preserved core baseline | PASS — exceeds 738 |
| Safe-archive and API-security focused suite | 12 passed |
| Federation exporter compatibility suite | 16 passed, 1 skipped (`requires_thehub`) |
| JSON Schemas | 43 compiled, 0 failures |
| Runtime `sys.path.insert` / `append` | 0 sites |
| Unsafe `ZipFile.extractall()` | 0 canonical sites |
| Nested tool suites | 60 passed (55 SATIM engine + 5 route findings) |
| PEP 517 editable install | PASS with local installed build toolchain and `--no-build-isolation` |
| Isolated wheel import smoke | PASS from `/tmp` for canonical packages, root compatibility facades, and FR24 runner |
| Wheel build/install smoke | PASS — wheel built and smoke-installed |
| Generated-artifact tracking gate | PASS — zero forbidden paths; stale runtime `.log` files removed |
| Deterministic source export | PASS — two 648-file exports had identical SHA-256 `6cd114568644ef2ebb5e60480727d1fdb7d0d8b1d6a95bfdc06b64a3af456fb3` and excluded frontend/data/generated artifacts |

## Environment qualification

An isolated build-dependency resolution attempt could not contact the sandbox package index. This is an execution-environment network limitation, not a metadata failure. The final validation uses the installed build toolchain with build isolation disabled and CI repeats the normal isolated build on GitHub-hosted runners.
