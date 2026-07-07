from __future__ import annotations
import pandas as pd
from .config import load_config

def confidence(row: pd.Series) -> float:
    score = 0.0
    score += 35 if pd.notna(row.get("timestamp")) else 0
    score += 30 if pd.notna(row.get("latitude")) and pd.notna(row.get("longitude")) else 0
    score += 15 if pd.notna(row.get("altitude")) else 0
    score += 10 if pd.notna(row.get("speed")) else 0
    score += 10 if pd.notna(row.get("callsign")) or pd.notna(row.get("registration")) else 0
    return min(score, 100.0)

def provenance_bucket_edges(config: dict) -> list[float]:
    scoring = config["scoring"]
    return [0, scoring["approximate"] - 1, scoring["high_confidence"] - 1, scoring["verified"] - 1, 100]

def score_tracks(df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    if config is None:
        config = load_config()
    out = df.copy()
    out["verification_score"] = out.apply(confidence, axis=1)
    out["provenance_level"] = pd.cut(
        out["verification_score"],
        provenance_bucket_edges(config),
        labels=["VISUAL_ESTIMATE", "APPROXIMATE", "HIGH_CONFIDENCE", "VERIFIED"],
        include_lowest=True,
    )
    return out
