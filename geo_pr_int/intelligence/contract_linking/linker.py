"""
Contract ↔ ILAP spatial linker for GEO-PR-INT.

For each ILAP candidate, finds nearby contracts within a configurable radius,
aggregates funding amounts and keywords, and computes a contract_match_score.
"""

import logging

import numpy as np
import pandas as pd

from config import SETTINGS
from utils.geo_helpers import metres_to_degrees_approx
from ingestion.contracts.loader import DEFAULT_SOURCE_WEIGHT

logger = logging.getLogger(__name__)

_SCORING   = SETTINGS["scoring"]
_RADIUS_M  = float(_SCORING.get("max_contract_proximity_m", 2000))


class ContractLinker:
    """Spatially links contracts to ILAP candidates using cKDTree proximity."""

    def __init__(self, radius_m: float = _RADIUS_M):
        self.radius_m = radius_m

    def link(
        self,
        candidates: pd.DataFrame,
        contracts: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        For each candidate, find contracts within radius_m and add:
          - matched_contract_count
          - total_obligated_amount
          - nearest_contract_m  (in metres, approximate)
          - contract_keywords   (union of matched_keywords lists)
          - top_vendor          (highest obligated_amount vendor)
          - contract_match_score (0–1)

        Parameters
        ----------
        candidates : ILAP candidates DataFrame with lat, lon
        contracts  : contract records DataFrame with lat, lon, obligated_amount,
                     matched_keywords, recipient_name_norm
        """
        from scipy.spatial import cKDTree

        candidates = candidates.copy()

        # Initialise output columns
        for col in ["matched_contract_count", "total_obligated_amount",
                    "nearest_contract_m", "contract_keywords",
                    "top_vendor", "contract_match_score"]:
            candidates[col] = 0 if col.endswith("count") else (0.0 if col != "contract_keywords" and col != "top_vendor" else "")

        if contracts.empty or "lat" not in contracts.columns or "lon" not in contracts.columns:
            logger.warning("Contract linker: no contract spatial data available")
            return candidates

        if candidates.empty or "lat" not in candidates.columns:
            return candidates

        # Build tree
        c_lats = pd.to_numeric(contracts["lat"], errors="coerce").fillna(0.0).values
        c_lons = pd.to_numeric(contracts["lon"], errors="coerce").fillna(0.0).values
        c_coords = np.column_stack([c_lats, c_lons])
        tree = cKDTree(c_coords)

        # Convert radius to degrees for approximate search
        radius_deg = metres_to_degrees_approx(self.radius_m)

        cand_coords = np.column_stack([
            pd.to_numeric(candidates["lat"], errors="coerce").fillna(0.0).values,
            pd.to_numeric(candidates["lon"], errors="coerce").fillna(0.0).values,
        ])

        # Prepare contract columns
        amounts  = pd.to_numeric(contracts.get("obligated_amount", 0), errors="coerce").fillna(0.0).values
        vendors  = contracts.get("recipient_name_norm", pd.Series("", index=contracts.index)).fillna("").values
        sg_wts   = pd.to_numeric(contracts.get("source_group_weight", DEFAULT_SOURCE_WEIGHT),
                                 errors="coerce").fillna(DEFAULT_SOURCE_WEIGHT).values
        src_grps = contracts.get("source_group", pd.Series("USASPENDING_FEDERAL", index=contracts.index)).fillna("").values

        def _keywords(idx_list: list[int]) -> str:
            kws: set = set()
            for i in idx_list:
                mkw = contracts.iloc[i].get("matched_keywords", [])
                if isinstance(mkw, list):
                    kws.update(mkw)
                elif isinstance(mkw, str) and mkw:
                    kws.update(mkw.split(","))
            return ",".join(sorted(kws))

        matched_counts, total_amounts, nearest_ms, kw_strs, top_vendors, scores, top_sources = (
            [], [], [], [], [], [], []
        )

        for i, coord in enumerate(cand_coords):
            indices = tree.query_ball_point(coord, r=radius_deg)
            if not indices:
                matched_counts.append(0)
                total_amounts.append(0.0)
                nearest_ms.append(0.0)
                kw_strs.append("")
                top_vendors.append("")
                scores.append(0.0)
                top_sources.append("")
                continue

            idx_arr = np.array(indices)
            local_amounts = amounts[idx_arr]
            local_weights = sg_wts[idx_arr]
            total_amt = float(local_amounts.sum())

            # Weight-adjusted total for scoring (COR3 dollars count more than SAM registry rows)
            weighted_amt = float((local_amounts * local_weights).sum())

            # Nearest distance in approximate metres
            dists, _ = tree.query(coord, k=1)
            nearest = float(dists * (111_320.0 + 111_320.0 * np.cos(np.radians(18.2))) / 2.0)

            # Top vendor and source group by weighted amount
            best_idx = idx_arr[int(np.argmax(local_amounts * local_weights))]
            top_v  = str(vendors[best_idx])
            top_sg = str(src_grps[best_idx])

            # Score: sigmoid on weighted obligation (normalised to $5M threshold)
            score = float(np.clip(1.0 - np.exp(-weighted_amt / 5e6), 0.0, 1.0))

            matched_counts.append(len(indices))
            total_amounts.append(total_amt)
            nearest_ms.append(nearest)
            kw_strs.append(_keywords(indices))
            top_vendors.append(top_v)
            scores.append(score)
            top_sources.append(top_sg)

        candidates["matched_contract_count"]  = matched_counts
        candidates["total_obligated_amount"]  = total_amounts
        candidates["nearest_contract_m"]      = nearest_ms
        candidates["contract_keywords"]       = kw_strs
        candidates["top_vendor"]              = top_vendors
        candidates["contract_match_score"]    = scores
        candidates["top_contract_source"]     = top_sources

        n_matched = int((np.array(matched_counts) > 0).sum())
        logger.info(
            f"Contract linker: {n_matched}/{len(candidates)} candidates matched "
            f"within {self.radius_m}m"
        )
        return candidates


def build_contract_spatial_index(contracts: pd.DataFrame):
    """Return a cKDTree built on contract (lat, lon) coordinates."""
    from scipy.spatial import cKDTree
    lats = pd.to_numeric(contracts["lat"], errors="coerce").fillna(0.0).values
    lons = pd.to_numeric(contracts["lon"], errors="coerce").fillna(0.0).values
    return cKDTree(np.column_stack([lats, lons]))


def summarise_contract_links(df: pd.DataFrame) -> dict:
    """Return summary stats for contract-linked candidates."""
    if df.empty:
        return {"total_matched": 0, "total_dollars_linked": 0.0}
    matched = int((df.get("matched_contract_count", 0) > 0).sum())
    dollars = float(df.get("total_obligated_amount", pd.Series(0)).sum())
    return {
        "total_matched":       matched,
        "pct_matched":         round(matched / len(df) * 100, 1) if len(df) else 0.0,
        "total_dollars_linked": dollars,
    }
