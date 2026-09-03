"""Equivalence test for the SATIM boundary fix: satim_geometry.py now imports
haversine_m from skywatcher.core.geo_utils instead of reaching into
skywatcher.correlation.footprint_proximity (a cross-boundary import fixed
during the module reorg). See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

from satim_geometry import haversine_m as satim_haversine_m
from skywatcher.core.geo_utils import haversine_m as core_haversine_m
from skywatcher.correlation.footprint_proximity import haversine_m as footprint_haversine_m

SAN_JUAN = (18.4655, -66.1057)
PONCE = (18.0111, -66.6141)


def test_all_three_import_paths_agree():
    assert satim_haversine_m is core_haversine_m
    assert footprint_haversine_m is core_haversine_m


def test_haversine_distance_unchanged():
    distance = core_haversine_m(*SAN_JUAN, *PONCE)
    assert satim_haversine_m(*SAN_JUAN, *PONCE) == distance
    assert footprint_haversine_m(*SAN_JUAN, *PONCE) == distance
    # Sanity check: San Juan -> Ponce is roughly 70-75 km as the crow flies.
    assert 65_000 < distance < 80_000
