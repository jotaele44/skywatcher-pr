"""
Contract source fetchers for GEO-PR-INT.

One module per source group — each exposes a fetch(use_cache=True) function
returning a DataFrame in the canonical OUTPUT_COLS schema.

Source groups:
  USASPENDING_FEDERAL     usaspending.py
  FSRS_SUBAWARDS          fsrs.py
  SAM_ENTITY_REGISTRY     sam_entity.py
  COR3_PR                 cor3_pr.py
  CONTRALOR_PR            contralor_pr.py
  OGPE_PR                 ogpe_pr.py
  OCE_PR                  oce_pr.py
  DCAA_CONTRACTOR_BASELINE dcaa.py
"""

from .usaspending import fetch as fetch_usaspending
from .fsrs import fetch as fetch_fsrs
from .sam_entity import fetch as fetch_sam
from .cor3_pr import fetch as fetch_cor3
from .contralor_pr import fetch as fetch_contralor
from .ogpe_pr import fetch as fetch_ogpe
from .oce_pr import fetch as fetch_oce
from .dcaa import fetch as fetch_dcaa

ALL_FETCHERS = {
    "USASPENDING_FEDERAL":      fetch_usaspending,
    "FSRS_SUBAWARDS":           fetch_fsrs,
    "SAM_ENTITY_REGISTRY":      fetch_sam,
    "COR3_PR":                  fetch_cor3,
    "CONTRALOR_PR":             fetch_contralor,
    "OGPE_PR":                  fetch_ogpe,
    "OCE_PR":                   fetch_oce,
    "DCAA_CONTRACTOR_BASELINE": fetch_dcaa,
}

__all__ = ["ALL_FETCHERS"] + [f"fetch_{k.lower()}" for k in [
    "usaspending", "fsrs", "sam", "cor3", "contralor", "ogpe", "oce", "dcaa"
]]
