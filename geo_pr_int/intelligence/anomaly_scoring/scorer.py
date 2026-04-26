"""
Multi-factor anomaly scoring for GEO-PR-INT.

Produces a unified_score (0–100) for each ILAP candidate by combining:
  - geometry_score   (linearity R² or physics_score fallback)  weight 0.30
  - ndvi_score       (NDVI disturbance signal)                 weight 0.25
  - hydro_score      (hydro proximity * (1 - karst_penalty))   weight 0.20
  - contract_score   (spatial contract match signal)            weight 0.25

Score tiers:
  CRITICAL  ≥ 80
  HIGH      ≥ 60
  MEDIUM    ≥ 40
  LOW       < 40
"""

import logging

import numpy as np
import pandas as pd

from config import SETTINGS

logger = logging.getLogger(__name__)

_SC = SETTINGS["scoring"]
_W_GEO      = float(_SC.get("geometry_weight",         0.30))
_W_NDVI     = float(_SC.get("ndvi_weight",             0.25))
_W_HYDRO    = float(_SC.get("hydro_proximity_weight",  0.20))
_W_CONTRACT = float(_SC.get("contract_match_weight",   0.25))
_SCALE      = float(_SC.get("score_scale",             100))

WEIGHTS = {
    "geometry":  _W_GEO,
    "ndvi":      _W_NDVI,
    "hydro":     _W_HYDRO,
    "contract":  _W_CONTRACT,
}

_TIERS = [
    (80, "CRITICAL"),
    (60, "HIGH"),
    (40, "MEDIUM"),
    (0,  "LOW"),
]


def _safe_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index)


def compute_unified_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add unified_score (0–100) and score_tier to candidates DataFrame.

    Uses best available signal for each factor:
      - geometry_score: linearity_r2 if in a linear corridor, else physics_score, else 0.5
      - ndvi_score:     ndvi_score column if present
      - hydro_score:    hydro_score > hydro_proximity_score if available
      - contract_score: contract_match_score
    """
    df = df.copy()

    # --- Geometry score ---
    if "linear_corridor" in df.columns and "linearity_r2" in df.columns:
        r2 = _safe_col(df, "linearity_r2")
        is_corr = df["linear_corridor"].fillna(False).astype(bool)
        phys = _safe_col(df, "physics_score", 0.5)
        geometry_score = np.where(is_corr, r2.clip(0.0, 1.0), phys)
    elif "physics_score" in df.columns:
        geometry_score = _safe_col(df, "physics_score", 0.5).values
    else:
        geometry_score = np.full(len(df), 0.5)

    # --- NDVI score ---
    ndvi_score = _safe_col(df, "ndvi_score").values

    # --- Hydro score ---
    if "hydro_score" in df.columns:
        hydro_score = _safe_col(df, "hydro_score").values
    else:
        hydro_score = _safe_col(df, "hydro_proximity_score").values

    # --- Contract score ---
    contract_score = _safe_col(df, "contract_match_score").values

    # --- Weighted sum → scale to [0, 100] ---
    raw = (
        geometry_score  * _W_GEO
        + ndvi_score    * _W_NDVI
        + hydro_score   * _W_HYDRO
        + contract_score * _W_CONTRACT
    )
    total_w = _W_GEO + _W_NDVI + _W_HYDRO + _W_CONTRACT
    unified = np.clip(raw / total_w, 0.0, 1.0) * _SCALE

    df["unified_score"] = unified

    # --- Tier ---
    def _tier(s: float) -> str:
        for threshold, label in _TIERS:
            if s >= threshold:
                return label
        return "LOW"

    df["score_tier"] = df["unified_score"].apply(_tier)

    logger.info(
        f"Scoring: mean={unified.mean():.1f}, "
        f"CRITICAL={int((unified >= 80).sum())}, "
        f"HIGH={int(((unified >= 60) & (unified < 80)).sum())}, "
        f"MEDIUM={int(((unified >= 40) & (unified < 60)).sum())}, "
        f"LOW={int((unified < 40).sum())}"
    )
    return df


def rank_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by unified_score descending and add unified_rank (1 = best)."""
    if "unified_score" not in df.columns:
        df = compute_unified_score(df)
    df = df.copy().sort_values("unified_score", ascending=False)
    df["unified_rank"] = np.arange(1, len(df) + 1, dtype=int)
    return df.reset_index(drop=True)


def top_n(df: pd.DataFrame, n: int = 50) -> pd.DataFrame:
    """Return top-n candidates by unified_score."""
    if "unified_score" not in df.columns:
        df = compute_unified_score(df)
    return df.nlargest(n, "unified_score").reset_index(drop=True)


def score_summary(df: pd.DataFrame) -> dict:
    """Return tier counts, mean score, and top-5 locations."""
    if df.empty:
        return {}

    scores = df.get("unified_score", pd.Series(dtype=float))
    tiers  = df.get("score_tier", pd.Series(dtype=str))

    top5 = df.nlargest(5, "unified_score") if "unified_score" in df.columns else df.head(5)
    top5_locs = [
        {"lat": float(r.get("lat", 0)), "lon": float(r.get("lon", 0)),
         "unified_score": float(r.get("unified_score", 0)),
         "infra_type": str(r.get("infra_type", "")),
         "corridor_id": int(r.get("corridor_id", 0))}
        for _, r in top5.iterrows()
    ]

    return {
        "total_candidates": len(df),
        "mean_score":        float(scores.mean()) if len(scores) else 0.0,
        "critical_count":    int((tiers == "CRITICAL").sum()),
        "high_count":        int((tiers == "HIGH").sum()),
        "medium_count":      int((tiers == "MEDIUM").sum()),
        "low_count":         int((tiers == "LOW").sum()),
        "top_5":             top5_locs,
    }
