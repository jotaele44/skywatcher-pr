"""geo_pr_int.config — loads settings.yaml and exposes a typed Settings object."""

import os
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "settings.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_settings(extra: dict | None = None) -> dict:
    """Load settings.yaml, merge optional overrides, and return the dict."""
    with open(_CONFIG_PATH, "r") as fh:
        cfg = yaml.safe_load(fh)
    if extra:
        cfg = _deep_merge(cfg, extra)
    return cfg


SETTINGS: dict = load_settings()

AOI: tuple = (
    SETTINGS["aoi"]["min_lon"],
    SETTINGS["aoi"]["min_lat"],
    SETTINGS["aoi"]["max_lon"],
    SETTINGS["aoi"]["max_lat"],
)

GEO_PR_INT_ROOT = Path(__file__).resolve().parent.parent
PR_INT_PATH = (GEO_PR_INT_ROOT / SETTINGS["sources"]["pr_intelligence_system"]).resolve()
CONTRACT_MASTER_PATH = (GEO_PR_INT_ROOT / SETTINGS["sources"]["contract_master_csv"]).resolve()
UNIFIED_AWARDS_PATH = (GEO_PR_INT_ROOT / SETTINGS["sources"]["unified_awards_csv"]).resolve()
