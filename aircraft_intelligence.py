"""Backward-compatible aircraft-profile facade.

The active API resolves source-declared identity/operator metadata and observed
activity statistics. Legacy mission-intent inference symbols remain available
only through lazy, warning-emitting compatibility access.
"""
from __future__ import annotations

import warnings

from skywatcher.core.known_operators import KNOWN_OPERATORS
from skywatcher.fpim.aircraft_profile import AircraftIntelligence, AircraftProfile, CALLSIGN_PREFIXES

__all__ = [
    "KNOWN_OPERATORS",
    "CALLSIGN_PREFIXES",
    "AircraftProfile",
    "AircraftIntelligence",
]

_LEGACY_NAMES = {"MissionAnalysis", "FlightMissionAnalyzer", "analyze_all_aircraft"}


def __getattr__(name: str):
    if name not in _LEGACY_NAMES:
        raise AttributeError(name)
    warnings.warn(
        f"aircraft_intelligence.{name} is quarantined because it infers flight intent; "
        "use observable route/activity descriptors instead",
        DeprecationWarning,
        stacklevel=2,
    )
    from skywatcher.legacy import quarantined_mission_inference as legacy

    return getattr(legacy, name)


if __name__ == "__main__":
    print("Aircraft Profile Layer\n")
    intelligence = AircraftIntelligence()
    for callsign in ["N5854Z", "C6062", "N767PD", "N684JB"]:
        print(intelligence.compile_intelligence_report(callsign))
