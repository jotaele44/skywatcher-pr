"""Equivalence test for the CORRIM consolidation: gis_intelligence.py is now a
backward-compat shim over skywatcher.corrim.gis_intelligence. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

from gis_intelligence import PuertoRicoInfrastructure as OldInfra
from gis_intelligence import haversine_nm as old_haversine_nm
from skywatcher.corrim.gis_intelligence import PuertoRicoInfrastructure as NewInfra
from skywatcher.corrim.gis_intelligence import haversine_nm as new_haversine_nm

SJU = (18.4386, -66.0010)
PSE = (18.0075, -66.5627)


def test_shim_reexports_identical_symbols():
    assert OldInfra is NewInfra
    assert old_haversine_nm is new_haversine_nm


def test_shim_functional_equivalence():
    assert old_haversine_nm(*SJU, *PSE) == new_haversine_nm(*SJU, *PSE)
    old_features = OldInfra().get_nearby_features(*SJU, radius_nm=100)
    new_features = NewInfra().get_nearby_features(*SJU, radius_nm=100)
    assert [f.feature_id for f in old_features] == [f.feature_id for f in new_features]
