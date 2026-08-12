"""Detector-family weights are reviewed magnitude constants (see
docs/SATIM_DETECTOR_WEIGHTS_RATIONALE.md). This asserts the properties that
actually hold — each weight is in (0, 1] and the dicts are non-empty — and
deliberately does NOT assert sum-to-1.0 (5/7 detectors intentionally over-sum
and rely on clamp01, so a simplex assertion would misrepresent the design)."""

from __future__ import annotations

import importlib

import pytest

# (module, weight-dict attribute)
DETECTOR_WEIGHTS = [
    ("satim_artifact_filter", "SIGNAL_WEIGHTS"),
    ("satim_artifact_filter", "LINK_WEIGHTS"),
    ("satim_cut_fill", "SIGNAL_WEIGHTS"),
    ("satim_cut_fill", "LINK_WEIGHTS"),
    ("satim_linear_corridor", "SIGNAL_WEIGHTS"),
    ("satim_linear_corridor", "LINK_WEIGHTS"),
    ("satim_patchwork", "SIGNAL_WEIGHTS"),
    ("satim_patchwork", "LINK_WEIGHTS"),
    ("satim_road_end", "SIGNAL_WEIGHTS"),
    ("satim_road_end", "LINK_WEIGHTS"),
    ("satim_water_feature", "SIGNAL_WEIGHTS"),
    ("satim_water_feature", "LINK_WEIGHTS"),
    ("satim_visual_route_gap", "SCORE_WEIGHTS"),
]


@pytest.mark.parametrize("module_name,attr", DETECTOR_WEIGHTS)
def test_each_weight_is_a_positive_unit_fraction(module_name, attr):
    weights = getattr(importlib.import_module(module_name), attr)
    assert isinstance(weights, dict) and weights, f"{module_name}.{attr} empty"
    for key, value in weights.items():
        v = float(value)
        assert 0.0 < v <= 1.0, f"{module_name}.{attr}[{key!r}] = {v} not in (0, 1]"


@pytest.mark.parametrize("module_name,attr", DETECTOR_WEIGHTS)
def test_weight_keys_are_unique_and_named(module_name, attr):
    weights = getattr(importlib.import_module(module_name), attr)
    keys = list(weights.keys())
    assert len(keys) == len(set(keys)), f"{module_name}.{attr} has duplicate keys"
    assert all(str(k) for k in keys), f"{module_name}.{attr} has empty key name"
