"""Repo-specific maintenance adapter for skywatcher-pr.

The generic maintenance core (models/state/detect/corrections/quarantine/report/
runner) now lives in the shared `prii_maintenance` package
(thehub-pr/packages/prii_maintenance, pinned in requirements-dev.txt). Only
`adapters/local.py` — the skywatcher-specific checks — stays vendored here; it
is passed into `prii_maintenance.run_maintenance(..., local_checks=local.run_checks)`.
Run via ``python3 scripts/run_maintenance.py --repo skywatcher-pr --mode audit``.
"""
