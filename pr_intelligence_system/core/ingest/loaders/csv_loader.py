import pandas as pd
import os
import logging

logger = logging.getLogger(__name__)


def load_csv(filepath: str) -> pd.DataFrame:
    """Load a CSV file and return a DataFrame with source metadata."""
    try:
        df = pd.read_csv(filepath)
        df['source_file'] = os.path.basename(filepath)
        df['source_format'] = 'csv'
        logger.info(f"Loaded CSV: {filepath} -> {len(df)} rows, {len(df.columns)} columns")
        return df
    except Exception as e:
        logger.error(f"Failed to load CSV {filepath}: {e}")
        raise
