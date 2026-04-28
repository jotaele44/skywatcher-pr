import rasterio
import rasterio.transform
import numpy as np
import pandas as pd
import os
import logging

logger = logging.getLogger(__name__)

MAX_RASTER_POINTS = 10000


def load_raster(
    filepath: str,
    max_points: int = MAX_RASTER_POINTS,
    min_valid_value: float = None,
) -> pd.DataFrame:
    """Load a raster file (GeoTIFF) and convert to point features DataFrame.

    Samples up to max_points valid pixels to keep memory bounded.
    Longitude is stored in 'lon', latitude in 'lat'.

    min_valid_value: if set, only pixels strictly greater than this value are
        kept (e.g. min_valid_value=0 to exclude ocean/nodata pixels in a DEM).
    """
    try:
        with rasterio.open(filepath) as src:
            raw = src.read(1, masked=True)   # masked array; nodata cells are masked
            data = raw.filled(np.nan).astype(float)
            transform = src.transform

            valid_mask = np.isfinite(data)

            if min_valid_value is not None:
                valid_mask = valid_mask & (data > min_valid_value)

            rows, cols = np.where(valid_mask)

            # Sample if too many valid pixels
            if len(rows) > max_points:
                rng = np.random.RandomState(42)
                indices = rng.choice(len(rows), max_points, replace=False)
                rows = rows[indices]
                cols = cols[indices]

            xs, ys = rasterio.transform.xy(transform, rows, cols)
            values = data[rows, cols]   # already float with nodata → NaN (filtered above)

            df = pd.DataFrame({
                'lat': np.array(ys),
                'lon': np.array(xs),
                'raster_value': values.astype(float),
            })
            df['source_file'] = os.path.basename(filepath)
            df['source_format'] = 'raster'
            logger.info(
                f"Loaded raster: {filepath} -> {len(df)} point features "
                f"(sampled from {valid_mask.sum()} valid pixels)"
            )
            return df

    except Exception as e:
        logger.error(f"Failed to load raster {filepath}: {e}")
        raise
