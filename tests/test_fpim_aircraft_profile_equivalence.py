"""Equivalence guard for the root FPIM compatibility facade."""

from aircraft_intelligence import AircraftIntelligence as OldIntel
from aircraft_intelligence import AircraftProfile as OldProfile
from skywatcher.fpim.aircraft_profile import AircraftIntelligence as NewIntel
from skywatcher.fpim.aircraft_profile import AircraftProfile as NewProfile


def test_shim_reexports_identical_classes():
    assert OldIntel is NewIntel
    assert OldProfile is NewProfile


def test_shim_functional_equivalence():
    old_profile = OldIntel("/nonexistent.db").lookup_aircraft("N5854Z")
    new_profile = NewIntel("/nonexistent.db").lookup_aircraft("N5854Z")
    assert old_profile == new_profile
    assert old_profile.operator == "Unknown"
    assert old_profile.primary_mission == "Unknown"
