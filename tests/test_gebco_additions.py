"""Tests for new GEBCO module additions: validate_bounds, mona_passage_profile, underwater_ridges.

The GEBCO terrain layer is an optional extra (`pip install -r requirements-geo.txt`).
These tests self-skip when numpy/scipy are absent so the core suite stays pure-Python.
"""

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy as np  # noqa: E402

from gebco.io import validate_bounds  # noqa: E402
from gebco.terrain import mona_passage_profile, underwater_ridges  # noqa: E402


# ── validate_bounds ───────────────────────────────────────────────────────────

def test_validate_bounds_valid_pr_region():
    validate_bounds(18.0, 18.5, -67.0, -65.5)  # should not raise


def test_validate_bounds_rejects_nyc():
    with pytest.raises(ValueError, match="Latitude bounds"):
        validate_bounds(40.4, 40.9, -74.3, -73.7)


def test_validate_bounds_rejects_inverted_lat():
    with pytest.raises(ValueError, match="lat_min"):
        validate_bounds(18.5, 18.0, -67.0, -65.5)


def test_validate_bounds_rejects_inverted_lon():
    with pytest.raises(ValueError, match="lon_min"):
        validate_bounds(18.0, 18.5, -65.5, -67.0)


def test_validate_bounds_rejects_lon_outside_pr():
    with pytest.raises(ValueError, match="Longitude bounds"):
        validate_bounds(18.0, 18.5, -70.0, -68.0)


def test_validate_bounds_exact_pr_edges():
    validate_bounds(17.92, 18.65, -67.30, -65.20)  # exact envelope — valid


# ── mona_passage_profile ──────────────────────────────────────────────────────

def _make_dem():
    lats = np.linspace(18.0, 18.5, 5)
    lons = np.linspace(-67.5, -65.5, 6)
    dem = np.full((5, 6), -500.0)
    dem[:, 3:] = -50.0  # eastern columns shallower
    return dem, lats, lons


def test_mona_passage_profile_returns_dict():
    dem, lats, lons = _make_dem()
    result = mona_passage_profile(dem, lats, lons)
    assert isinstance(result, dict)


def test_mona_passage_profile_keys():
    dem, lats, lons = _make_dem()
    result = mona_passage_profile(dem, lats, lons)
    assert set(result.keys()) == {"lat_profile", "mean_depth_m", "min_depth_m", "max_depth_m"}


def test_mona_passage_profile_lat_length():
    dem, lats, lons = _make_dem()
    result = mona_passage_profile(dem, lats, lons)
    assert len(result["lat_profile"]) == len(lats)
    assert len(result["mean_depth_m"]) == len(lats)


def test_mona_passage_profile_depths_negative():
    dem, lats, lons = _make_dem()
    result = mona_passage_profile(dem, lats, lons)
    assert result["min_depth_m"] < 0
    assert result["max_depth_m"] < 0


# ── underwater_ridges ─────────────────────────────────────────────────────────

def test_underwater_ridges_returns_list():
    dem = np.array([[-300, -100, -300], [-300, -100, -300], [-300, -300, -300]], dtype=float)
    ridges = underwater_ridges(dem, dx=500, dy=500, threshold_m=-150)
    assert isinstance(ridges, list)


def test_underwater_ridges_detects_local_max():
    # Central cell at -50 m is a local max, shallower than threshold -100 m
    dem = np.array([[-200, -200, -200], [-200, -50, -200], [-200, -200, -200]], dtype=float)
    ridges = underwater_ridges(dem, dx=500, dy=500, threshold_m=-100)
    assert (1, 1) in ridges


def test_underwater_ridges_excludes_above_sea_level():
    # Positive elevation (land) should not be classified as a ridge
    dem = np.array([[100, 200, 100], [100, 300, 100], [100, 100, 100]], dtype=float)
    ridges = underwater_ridges(dem, dx=500, dy=500, threshold_m=-100)
    assert len(ridges) == 0


def test_underwater_ridges_excludes_below_threshold():
    # Feature at -500 m is below the -100 m threshold
    dem = np.array([[-600, -600, -600], [-600, -500, -600], [-600, -600, -600]], dtype=float)
    ridges = underwater_ridges(dem, dx=500, dy=500, threshold_m=-100)
    assert (1, 1) not in ridges
