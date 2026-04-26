"""
Hydro proximity linker for GEO-PR-INT.

Enriches ILAP candidates with hydrology scores: stream proximity,
karst zone flags, and river basin attribution.
"""

import logging

import numpy as np
import pandas as pd

from config import SETTINGS
from ingestion.hydro.hydrography import compute_hydro_proximity

logger = logging.getLogger(__name__)

_HYDRO_CFG = SETTINGS.get("hydro", {})
_BUFFER_M  = float(_HYDRO_CFG.get("buffer_m", 500))


class HydroLinker:
    """Links ILAP candidates to hydrological features."""

    def __init__(self, buffer_m: float = _BUFFER_M):
        self.buffer_m = buffer_m

    def link(
        self,
        candidates: pd.DataFrame,
        hydro: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Enrich candidates with:
          - hydro_proximity_score  (0–1, from compute_hydro_proximity)
          - karst_zone             (bool)
          - karst_penalty          (0 or 0.5)
          - river_basin            (str)
          - hydro_score            (proximity * (1 - karst_penalty))

        Parameters
        ----------
        candidates : ILAP candidates with lat, lon
        hydro      : hydro feature grid from load_hydro_features()
        """
        if candidates.empty:
            return candidates

        # Compute proximity via cKDTree
        candidates = compute_hydro_proximity(candidates, hydro, buffer_m=self.buffer_m)

        # Copy nearest-neighbour hydro attributes
        candidates = self._attach_hydro_attrs(candidates, hydro)

        # Final hydro score
        prox = candidates["hydro_proximity_score"].fillna(0.0)
        karst_pen = candidates.get("karst_penalty", pd.Series(0.0, index=candidates.index)).fillna(0.0)
        candidates["hydro_score"] = (prox * (1.0 - karst_pen)).clip(0.0, 1.0)

        logger.info(
            f"HydroLinker: mean hydro_score={candidates['hydro_score'].mean():.3f}, "
            f"karst_flagged={candidates.get('karst_zone', pd.Series(False)).sum()}"
        )
        return candidates

    def _attach_hydro_attrs(
        self,
        candidates: pd.DataFrame,
        hydro: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Attach karst_zone, karst_penalty, river_basin from the nearest hydro node
        to each candidate using cKDTree.
        """
        from scipy.spatial import cKDTree

        candidates = candidates.copy()

        if hydro.empty:
            candidates["karst_zone"]   = False
            candidates["karst_penalty"] = 0.0
            candidates["river_basin"]   = "unknown"
            return candidates

        hydro_coords = hydro[["lat", "lon"]].values.astype(float)
        cand_coords  = candidates[["lat", "lon"]].values.astype(float)
        tree = cKDTree(hydro_coords)
        _, idxs = tree.query(cand_coords, k=1)

        for col, default in [("karst_zone", False), ("karst_penalty", 0.0), ("river_basin", "unknown")]:
            if col in hydro.columns:
                candidates[col] = hydro.iloc[idxs][col].values
            else:
                candidates[col] = default

        return candidates


def flag_karst_zones(
    candidates: pd.DataFrame,
    hydro: pd.DataFrame,
) -> pd.DataFrame:
    """Standalone helper: add karst_zone and karst_penalty to candidates."""
    linker = HydroLinker()
    return linker._attach_hydro_attrs(candidates, hydro)
