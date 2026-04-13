import numpy as np
import pandas as pd
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = os.path.join('data', 'output', 'snapshots')


def load_snapshots(snapshot_dir: str = SNAPSHOT_DIR) -> list:
    """Load all previously saved snapshot CSVs from snapshot_dir.

    Returns a list of DataFrames.  Missing or unreadable files are skipped
    with a warning.
    """
    snapshots = []

    if not os.path.isdir(snapshot_dir):
        logger.info(f"Snapshot directory not found: '{snapshot_dir}' – no history loaded")
        return snapshots

    snapshot_files = sorted(
        f for f in os.listdir(snapshot_dir)
        if f.startswith('snapshot_') and f.endswith('.csv')
    )

    for filename in snapshot_files:
        filepath = os.path.join(snapshot_dir, filename)
        try:
            df = pd.read_csv(filepath)
            df['snapshot_file'] = filename
            snapshots.append(df)
            logger.info(f"Loaded snapshot: {filename} ({len(df)} rows)")
        except Exception as exc:
            logger.warning(f"Could not load snapshot '{filename}': {exc}")

    logger.info(f"Total snapshots loaded: {len(snapshots)}")
    return snapshots


def compute_persistence(df: pd.DataFrame, snapshot_dir: str = SNAPSHOT_DIR) -> pd.DataFrame:
    """Compute how many times each cell_id has been detected historically.

    Loads all snapshots and counts prior occurrences of each cell_id.
    The current detection always contributes +1 on top of the historical count.

    Adds: persistence (integer ≥ 1).
    """
    df = df.copy()

    if 'cell_id' not in df.columns:
        logger.warning("'cell_id' column not found – setting persistence=1 for all rows")
        df['persistence'] = 1
        return df

    snapshots = load_snapshots(snapshot_dir)

    if not snapshots:
        df['persistence'] = 1
        logger.info("No historical snapshots – persistence initialised to 1")
        return df

    all_historical = pd.concat(snapshots, ignore_index=True)

    if 'cell_id' not in all_historical.columns:
        logger.warning("Historical snapshots lack 'cell_id' – setting persistence=1")
        df['persistence'] = 1
        return df

    historical_counts = all_historical['cell_id'].value_counts().to_dict()
    df['persistence'] = df['cell_id'].map(
        lambda cid: int(historical_counts.get(cid, 0)) + 1
    )

    logger.info(
        f"Persistence: min={df['persistence'].min()}, "
        f"max={df['persistence'].max()}, "
        f"mean={df['persistence'].mean():.2f}"
    )
    return df


def save_snapshot(df: pd.DataFrame, snapshot_dir: str = SNAPSHOT_DIR) -> str:
    """Save the current DataFrame as a UTC-timestamped snapshot CSV.

    Returns the path to the saved file.
    """
    os.makedirs(snapshot_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename  = f'snapshot_{timestamp}.csv'
    filepath  = os.path.join(snapshot_dir, filename)

    df.to_csv(filepath, index=False)
    logger.info(f"Snapshot saved: '{filepath}' ({len(df)} rows)")
    return filepath
