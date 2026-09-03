# FR24 processing package

import sys
from pathlib import Path

# fr24/calibration/* imports src/skywatcher/core (see
# docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md). "src" is only on sys.path
# automatically under pytest (pyproject.toml's pythonpath setting); standalone
# entry points (`python -m fr24.satim_engine`) need it bootstrapped here.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
