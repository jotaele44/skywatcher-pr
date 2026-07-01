from __future__ import annotations
import pandas as pd

def confidence(row: pd.Series) -> float:
    score = 0.0
    score += 35 if pd.notna(row.get("timestamp")) else 0
    score += 30 if pd.notna(row.get("latitude")) and pd.notna(row.get("longitude")) else 0
    score += 15 if pd.notna(row.get("altitude")) else 0
    score += 10 if pd.notna(row.get("speed")) else 0
    score += 10 if pd.notna(row.get("callsign")) or pd.notna(row.get("registration")) else 0
    return min(score, 100.0)

def score_tracks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["verification_score"] = out.apply(confidence, axis=1)
    out["provenance_level"] = pd.cut(out["verification_score"], [0,59,79,94,100], labels=["VISUAL_ESTIMATE","APPROXIMATE","HIGH_CONFIDENCE","VERIFIED"], include_lowest=True)
    return out
