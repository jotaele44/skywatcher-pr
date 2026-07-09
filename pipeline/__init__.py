"""Pipeline package for Spiderweb / RLSM normalization modules."""

import sys
from pathlib import Path

# pipeline/* modules are backward-compat shims delegating to src/skywatcher/core
# (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md). "src" is only on sys.path
# automatically under pytest (pyproject.toml's pythonpath setting); standalone
# entry points (scripts/*.py, `python -m fr24.satim_engine`) need it bootstrapped
# here so `from skywatcher.core... import ...` resolves regardless of caller.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
