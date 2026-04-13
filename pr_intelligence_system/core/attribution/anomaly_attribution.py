import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Classification thresholds (physics_score boundaries)
THRESHOLD_ANOMALY        = 0.75
THRESHOLD_INFRASTRUCTURE = 0.55
THRESHOLD_NATURAL        = 0.35

CLASSIFICATION_LABELS = ['anomaly', 'infrastructure', 'natural', 'noise']


def classify_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Classify each observation using physics_score thresholds.

    Labels:
        anomaly        physics_score >= 0.75
        infrastructure 0.55 <= physics_score < 0.75
        natural        0.35 <= physics_score < 0.55
        noise          physics_score < 0.35

    Adds: classification.
    """
    df = df.copy()

    if 'physics_score' not in df.columns:
        logger.warning("physics_score not found – defaulting all to 'noise'")
        df['classification'] = 'noise'
        return df

    scores = df['physics_score'].fillna(0.0).values.astype(float)

    classification = np.where(
        scores >= THRESHOLD_ANOMALY, 'anomaly',
        np.where(
            scores >= THRESHOLD_INFRASTRUCTURE, 'infrastructure',
            np.where(
                scores >= THRESHOLD_NATURAL, 'natural',
                'noise'
            )
        )
    )

    df['classification'] = classification

    counts = pd.Series(classification).value_counts().to_dict()
    logger.info(f"Classification results: {counts}")
    return df


def compute_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Assign a confidence score ∈ [0, 1] to each classification.

    Confidence is proportional to how far the physics_score falls
    within its respective class interval.

    Adds: confidence.
    """
    df = df.copy()

    if 'physics_score' not in df.columns:
        df['confidence'] = 0.5
        return df

    scores = df['physics_score'].fillna(0.0).values.astype(float)

    confidence = np.where(
        scores >= THRESHOLD_ANOMALY,
        np.clip(0.6 + 0.4 * (scores - THRESHOLD_ANOMALY) / (1.0 - THRESHOLD_ANOMALY), 0.0, 1.0),
        np.where(
            scores >= THRESHOLD_INFRASTRUCTURE,
            np.clip(0.5 + 0.1 * (scores - THRESHOLD_INFRASTRUCTURE)
                    / (THRESHOLD_ANOMALY - THRESHOLD_INFRASTRUCTURE), 0.0, 1.0),
            np.where(
                scores >= THRESHOLD_NATURAL,
                np.clip(0.3 + 0.2 * (scores - THRESHOLD_NATURAL)
                        / (THRESHOLD_INFRASTRUCTURE - THRESHOLD_NATURAL), 0.0, 1.0),
                np.clip(0.1 + 0.2 * scores / THRESHOLD_NATURAL, 0.0, 1.0),
            )
        )
    )

    df['confidence'] = confidence
    logger.info(f"Confidence: mean={confidence.mean():.4f}, std={confidence.std():.4f}")
    return df


def rank_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Sort observations by physics_score (desc) then confidence (desc).

    Adds: anomaly_rank (1-based, 1 = highest-priority observation).
    """
    df = df.copy()

    sort_cols = []
    if 'physics_score' in df.columns:
        sort_cols.append('physics_score')
    if 'confidence' in df.columns:
        sort_cols.append('confidence')

    if sort_cols:
        df = df.sort_values(sort_cols, ascending=[False] * len(sort_cols))

    df = df.reset_index(drop=True)
    df['anomaly_rank'] = np.arange(1, len(df) + 1)

    logger.info(f"Anomaly ranking complete: {len(df)} observations")
    return df
