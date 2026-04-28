"""
Landsat Collection 2 Level-2 Fetcher
=====================================
Source : s3://usgs-landsat (public, unsigned boto3)
Path   : collection02/level-2/standard/oli-tirs/{year}/{path:03d}/{row:03d}/{scene_id}/

Downloads surface-reflectance bands B3 (green), B4 (red), B5 (NIR) for
Puerto Rico WRS-2 path/rows, applies Collection 2 scale factors, and
computes NDWI = (green - NIR) / (green + NIR + 1e-10).

Output: lat, lon, raster_value (B4 scaled reflectance), ndwi, band='SR_B4',
        acquisition_date, source_file, source_format='landsat_c2'.
On any failure (including RequesterPays errors) returns empty DataFrame.
"""

import os
import logging
import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

S3_BUCKET_LANDSAT = 'usgs-landsat'
LC2_BASE_PREFIX   = 'collection02/level-2/standard/oli-tirs'
DEFAULT_CACHE_DIR  = os.path.join(FETCHER_CACHE_ROOT, 'landsat_c2')
# WRS-2 path/rows covering Puerto Rico
PR_WRS2_PATHROWS  = [(4, 47), (5, 47)]
MAX_SCENES        = 2
# Collection 2 surface reflectance scale / offset (USGS LSDS-1619 §3.1.2)
SR_SCALE_FACTOR   = 0.0000275
SR_ADD_OFFSET     = -0.2


def _list_landsat_scenes(s3_client, year: str, path: int, row: int, max_scenes: int) -> list:
    """List scene-directory prefixes for a given WRS-2 path/row and year."""
    prefix = f'{LC2_BASE_PREFIX}/{year}/{path:03d}/{row:03d}/'
    logger.debug(f"Landsat C2: listing s3://{S3_BUCKET_LANDSAT}/{prefix}")
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_LANDSAT, Prefix=prefix, Delimiter='/', MaxKeys=50
        )
        return [p['Prefix'] for p in resp.get('CommonPrefixes', [])][:max_scenes]
    except Exception as exc:
        logger.debug(f"Landsat C2: scene listing failed for {prefix}: {exc}")
        return []


def _scene_date_from_prefix(scene_prefix: str) -> str:
    """Parse acquisition date from scene directory name.

    Format: LC0X_L2SP_{PPP}{RRR}_{YYYYMMDD}_...
    Returns 'YYYY-MM-DD' or 'unknown'.
    """
    try:
        dirname = os.path.basename(scene_prefix.rstrip('/'))
        parts   = dirname.split('_')
        s       = parts[3]   # zero-indexed: LC09 / L2SP / 004047 / 20240115 / ...
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    except Exception:
        return 'unknown'


def _download_band_tif(s3_client, scene_prefix: str, band_suffix: str, output_dir: str):
    """Download a single band GeoTIFF; return local path or None on failure."""
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_LANDSAT, Prefix=scene_prefix, MaxKeys=200
        )
        key = next(
            (obj['Key'] for obj in resp.get('Contents', [])
             if obj['Key'].endswith(band_suffix)),
            None,
        )
        if key is None:
            logger.debug(f"Landsat C2: {band_suffix} not found in {scene_prefix}")
            return None

        filename   = key.replace('/', '_')
        local_path = os.path.join(output_dir, filename)

        if os.path.exists(local_path):
            logger.debug(f"Landsat C2: cache hit {filename}")
            return local_path

        logger.info(f"Landsat C2 S3: downloading {key}")
        s3_client.download_file(S3_BUCKET_LANDSAT, key, local_path)
        return local_path

    except Exception as exc:
        err_str = str(exc)
        if 'RequestorPaysBucket' in err_str or 'RequesterPays' in err_str:
            logger.warning(
                f"Landsat C2: bucket is RequesterPays for {band_suffix} in {scene_prefix} — skipping"
            )
        else:
            logger.debug(f"Landsat C2: download failed for {band_suffix}: {exc}")
        return None


def _aoi_filter(df: pd.DataFrame, aoi: tuple) -> pd.DataFrame:
    min_lon, min_lat, max_lon, max_lat = aoi
    mask = (
        (df['lat'] >= min_lat) & (df['lat'] <= max_lat)
        & (df['lon'] >= min_lon) & (df['lon'] <= max_lon)
    )
    return df[mask].reset_index(drop=True)


def fetch_landsat_c2(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
    max_scenes: int = MAX_SCENES,
    output_dir: str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Fetch Landsat Collection 2 Level-2 surface reflectance from AWS S3.

    Searches WRS-2 path/rows (4/47, 5/47) covering Puerto Rico.
    Downloads B3 (green), B4 (red), B5 (NIR); applies C2 scale factors;
    computes NDWI.  Gracefully skips RequesterPays scenes.

    Returns DataFrame with: lat, lon, raster_value (B4 reflectance), ndwi,
    band='SR_B4', acquisition_date, source_file, source_format='landsat_c2'.
    On any failure returns empty DataFrame.
    """
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        from core.ingest.loaders.raster_loader import load_raster

        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        os.makedirs(output_dir, exist_ok=True)

        year = date_range[0].replace('-', '')[:4]

        all_scene_prefixes = []
        for path, row in PR_WRS2_PATHROWS:
            scenes = _list_landsat_scenes(s3, year, path, row, max_scenes)
            all_scene_prefixes.extend(scenes)
            if len(all_scene_prefixes) >= max_scenes:
                break

        all_scene_prefixes = all_scene_prefixes[:max_scenes]

        if not all_scene_prefixes:
            logger.warning(
                f"Landsat C2: no scenes found for year {year} in PR path/rows "
                f"{PR_WRS2_PATHROWS} – returning empty DataFrame"
            )
            return empty_fetcher_df(['ndwi', 'band', 'acquisition_date'])

        all_dfs = []

        for scene_prefix in all_scene_prefixes:
            acq_date = _scene_date_from_prefix(scene_prefix)

            b4_path = _download_band_tif(s3, scene_prefix, '_SR_B4.TIF', output_dir)
            if b4_path is None:
                continue

            b3_path = _download_band_tif(s3, scene_prefix, '_SR_B3.TIF', output_dir)
            b5_path = _download_band_tif(s3, scene_prefix, '_SR_B5.TIF', output_dir)

            df_b4 = load_raster(b4_path)
            if len(df_b4) == 0:
                continue

            # Apply Collection 2 scale factors and AOI filter
            df_b4['raster_value'] = (
                df_b4['raster_value'].astype(float) * SR_SCALE_FACTOR + SR_ADD_OFFSET
            )
            df_b4['raster_value'] = df_b4['raster_value'].clip(0.0, 1.0)
            df_b4 = _aoi_filter(df_b4, aoi)

            if len(df_b4) == 0:
                logger.info(f"Landsat C2: {os.path.basename(b4_path)} has no data in AOI")
                continue

            # Compute NDWI if green + NIR available
            if b3_path is not None and b5_path is not None:
                try:
                    df_b3 = _aoi_filter(load_raster(b3_path), aoi)
                    df_b5 = _aoi_filter(load_raster(b5_path), aoi)

                    min_len = min(len(df_b4), len(df_b3), len(df_b5))
                    green = (df_b3['raster_value'].values[:min_len].astype(float)
                             * SR_SCALE_FACTOR + SR_ADD_OFFSET)
                    nir   = (df_b5['raster_value'].values[:min_len].astype(float)
                             * SR_SCALE_FACTOR + SR_ADD_OFFSET)
                    ndwi  = (green - nir) / (green + nir + 1e-10)

                    df_b4 = df_b4.iloc[:min_len].copy()
                    df_b4['ndwi'] = ndwi
                except Exception as exc:
                    logger.debug(f"Landsat C2: NDWI computation failed: {exc}")
                    df_b4['ndwi'] = np.nan
            else:
                df_b4['ndwi'] = np.nan

            df_b4['band']            = 'SR_B4'
            df_b4['acquisition_date'] = acq_date
            df_b4['source_format']   = 'landsat_c2'
            df_b4['source_file']     = os.path.basename(b4_path)

            register_loaded_file(b4_path, 'landsat_c2', len(df_b4))
            all_dfs.append(df_b4)
            logger.info(f"Landsat C2: {len(df_b4)} points from {acq_date}")

        if not all_dfs:
            return empty_fetcher_df(['ndwi', 'band', 'acquisition_date'])

        result = pd.concat(all_dfs, ignore_index=True)
        result = validate_fetcher_output(result, 'LandsatC2')
        logger.info(f"Landsat C2: {len(result)} total point features returned")
        return result

    except ImportError as exc:
        logger.warning(f"Landsat C2: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['ndwi', 'band', 'acquisition_date'])
    except Exception as exc:
        logger.warning(f"Landsat C2 fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['ndwi', 'band', 'acquisition_date'])
