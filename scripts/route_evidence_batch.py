#!/usr/bin/env python3
"""Inventory a screenshot/PDF/ZIP/mixed batch and emit a deterministic skill plan."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from skywatcher.evidence_router import main


if __name__ == "__main__":
    raise SystemExit(main())
