#!/usr/bin/env python3
"""Backward-compat shim. Logic moved to skywatcher.core.ontology_gate.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.ontology_gate import REQUIRED_CONFIGS, main, run_gate

__all__ = ["REQUIRED_CONFIGS", "main", "run_gate"]

if __name__ == "__main__":
    raise SystemExit(main())
