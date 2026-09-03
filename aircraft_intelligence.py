"""Backward-compat shim.

AircraftProfile/AircraftIntelligence -> skywatcher.fpim.aircraft_profile
KNOWN_OPERATORS -> skywatcher.core.known_operators (ground-truth registry, not inference)
FlightMissionAnalyzer/_deduce_mission/MissionAnalysis/analyze_all_aircraft are
QUARANTINED -> skywatcher.legacy.quarantined_mission_inference. Kept importable
here ONLY for backward compatibility; NOT part of FPIM's active API. Do not
infer intent or operational purpose anywhere in this pipeline. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

# "src" is only on sys.path automatically under pytest (pyproject.toml's
# pythonpath setting); bootstrap it here so this shim resolves regardless of
# the calling entry point (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from skywatcher.core.known_operators import KNOWN_OPERATORS
from skywatcher.fpim.aircraft_profile import (
    AIRCRAFT_TYPE_MISSIONS,
    CALLSIGN_PREFIXES,
    AircraftIntelligence,
    AircraftProfile,
)
from skywatcher.legacy.quarantined_mission_inference import (
    FlightMissionAnalyzer,
    MissionAnalysis,
    analyze_all_aircraft,
)

__all__ = [
    "KNOWN_OPERATORS",
    "CALLSIGN_PREFIXES",
    "AIRCRAFT_TYPE_MISSIONS",
    "AircraftProfile",
    "AircraftIntelligence",
    "MissionAnalysis",
    "FlightMissionAnalyzer",
    "analyze_all_aircraft",
]

if __name__ == "__main__":
    print("Aircraft Intelligence Layer\n")
    intel = AircraftIntelligence()
    for callsign in ["N5854Z", "C6062", "N767PD", "N684JB"]:
        print(intel.compile_intelligence_report(callsign))
