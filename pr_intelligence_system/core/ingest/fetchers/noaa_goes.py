"""
NOAA GOES-16/17/18 ABI Fetcher
================================
Fetches NOAA GOES ABI Level-2 products from AWS public S3 buckets
(s3://noaa-goes16, s3://noaa-goes17, s3://noaa-goes18).
No credentials required (unsigned boto3 access).

GOES ABI imagery uses a satellite fixed-grid coordinate system that must be
reprojected to geographic lat/lon using the GOES-R Series Product Definition
and Users' Guide (PUG) §4.2.8 formula.

Default product: ABI-L2-CMIPF (Cloud and Moisture Image, Full Disk)
Default band:    13 (10.3 µm thermal IR — most useful for sea surface temp
                 and cloud-top anomaly detection)

Output: DataFrame with lat, lon, raster_value (brightness temperature K),
        source_file, source_format='noaa_goes', band, scan_start_time.
"""

import os
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

from config.fetcher_config import DEFAULT_AOI, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output
from core.ingest.registry import register_loaded_file

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(FETCHER_CACHE_ROOT, 'goes')
MAX_RASTER_POINTS = 10_000

S3_BUCKETS = {
    'goes16': 'noaa-goes16',
    'goes17': 'noaa-goes17',
    'goes18': 'noaa-goes18',
}

# GOES-16 sub-satellite point longitude
SAT_LON = {
    'goes16': -75.0,
    'goes17': -137.0,
    'goes18': -137.2,
}


def _goes_fixedgrid_to_latlon(
    x: np.ndarray,
    y: np.ndarray,
    sat_height_m: float = 35_786_023.0,
    sat_lon_deg: float = -75.0,
    r_eq: float = 6_378_137.0,
    r_pol: float = 6_356_752.3142,
) -> tuple:
    """Convert GOES ABI fixed-grid scan angles (radians) to geographic lat/lon.

    Implements the exact reprojection formula from GOES-R Series PUG Vol.3 §4.2.8.
    Pixels outside the Earth disk are returned as NaN.
    """
    H     = sat_height_m + r_eq
    lon_0 = np.radians(sat_lon_deg)

    a_val = (
        np.sin(x) ** 2
        + np.cos(x) ** 2 * (np.cos(y) ** 2 + (r_eq / r_pol) ** 2 * np.sin(y) ** 2)
    )
    b_val = -2.0 * H * np.cos(x) * np.cos(y)
    c_val = H ** 2 - r_eq ** 2

    discriminant = b_val ** 2 - 4.0 * a_val * c_val
    valid = discriminant >= 0.0

    rs = np.full_like(x, np.nan, dtype=float)
    rs[valid] = (-b_val[valid] - np.sqrt(discriminant[valid])) / (2.0 * a_val[valid])

    sx = rs * np.cos(x) * np.cos(y)
    sy = -rs * np.sin(x)
    sz = rs * np.cos(x) * np.sin(y)

    lat_rad = np.arctan(
        (r_eq / r_pol) ** 2 * sz / np.sqrt((H - sx) ** 2 + sy ** 2)
    )
    lon_rad = lon_0 - np.arctan(sy / (H - sx))

    lat_deg = np.degrees(lat_rad)
    lon_deg = np.degrees(lon_rad)

    lat_deg[~valid] = np.nan
    lon_deg[~valid] = np.nan

    return lat_deg, lon_deg


def _rad_to_brightness_temp(rad: np.ndarray, fk1: float, fk2: float, bc1: float, bc2: float) -> np.ndarray:
    """Convert ABI radiance to brightness temperature (Kelvin).

    Formula: T = (fk2 / log(fk1/L + 1) - bc1) / bc2
    """
    with np.errstate(divide='ignore', invalid='ignore'):
        T = (fk2 / np.log(fk1 / rad + 1.0) - bc1) / bc2
    T[rad <= 0] = np.nan
    return T


def _list_s3_files_for_hour(s3_client, bucket: str, product: str, band: int,
                             dt: datetime) -> list:
    """List .nc files for a specific product/band/hour in the S3 bucket."""
    year        = dt.strftime('%Y')
    day_of_year = dt.strftime('%j')
    hour        = dt.strftime('%H')
    band_str    = f'C{band:02d}'

    # Use directory-level prefix without OR_ fragment so we enumerate all files
    prefix = f'{product}/{year}/{day_of_year}/{hour}/'
    logger.debug(f"NOAA GOES: listing s3://{bucket}/{prefix}")
    try:
        resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=50)
        keys = [
            obj['Key'] for obj in resp.get('Contents', [])
            if obj['Key'].endswith('.nc') and band_str in obj['Key']
        ]
        return keys
    except Exception as exc:
        logger.debug(f"NOAA GOES S3 listing failed for {prefix}: {exc}")
        return []


def _find_recent_files(s3_client, bucket: str, product: str, band: int,
                       start_dt: datetime, max_lookback_hours: int = 24) -> list:
    """Search backwards from start_dt until files are found (up to max_lookback_hours)."""
    for hours_back in range(0, max_lookback_hours + 1):
        dt = start_dt - timedelta(hours=hours_back)
        keys = _list_s3_files_for_hour(s3_client, bucket, product, band, dt)
        if keys:
            logger.info(
                f"NOAA GOES: found {len(keys)} file(s) at "
                f"{dt.strftime('%Y-%j-%H')} ({hours_back}h back)"
            )
            return keys
    return []


def fetch_noaa_goes(
    aoi: tuple = DEFAULT_AOI,
    satellite: str = 'goes16',
    product: str = 'ABI-L2-CMIPF',
    band: int = 13,
    datetime_utc: str = None,
    max_files: int = 1,
    output_dir: str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Fetch NOAA GOES ABI imagery from AWS S3 (no credentials required).

    Searches backwards up to 24 hours from the requested time so the fetcher
    succeeds even if the current hour has no files yet.

    Returns DataFrame with: lat, lon, raster_value (brightness temp K),
    source_file, source_format='noaa_goes', band, scan_start_time.
    On any failure returns empty DataFrame.
    """
    try:
        import boto3
        import netCDF4 as nc4
        from botocore import UNSIGNED
        from botocore.config import Config

        bucket  = S3_BUCKETS.get(satellite, S3_BUCKETS['goes16'])
        sat_lon = SAT_LON.get(satellite, -75.0)

        s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
        os.makedirs(output_dir, exist_ok=True)

        # Resolve start datetime
        if datetime_utc is not None:
            try:
                start_dt = datetime.strptime(datetime_utc, '%Y%m%d_%H%M').replace(tzinfo=timezone.utc)
            except ValueError:
                start_dt = datetime.now(timezone.utc)
        else:
            start_dt = datetime.now(timezone.utc)

        keys = _find_recent_files(s3, bucket, product, band, start_dt)
        if not keys:
            logger.warning(
                f"NOAA GOES: no files found within 24h of "
                f"{start_dt.strftime('%Y-%m-%d %H:00 UTC')} — returning empty DataFrame"
            )
            return empty_fetcher_df(['band', 'scan_start_time'])

        all_dfs = []

        for key in keys[:max_files]:
            filename   = os.path.basename(key)
            local_path = os.path.join(output_dir, filename)

            if os.path.exists(local_path):
                logger.info(f"NOAA GOES: cache hit {filename}")
            else:
                logger.info(f"NOAA GOES S3: downloading {key}")
                try:
                    s3.download_file(bucket, key, local_path)
                except Exception as exc:
                    logger.warning(f"NOAA GOES: download failed for {key}: {exc}")
                    continue

            try:
                ds = nc4.Dataset(local_path, 'r')

                x_angles = ds.variables['x'][:]
                y_angles = ds.variables['y'][:]
                xx, yy   = np.meshgrid(x_angles, y_angles)

                rad_var = ds.variables['Rad']
                rad     = rad_var[:].data.astype(float)
                nodata  = getattr(rad_var, '_FillValue', None)
                if nodata is not None:
                    rad[rad == nodata] = np.nan

                try:
                    fk1 = float(ds.variables['planck_fk1'][:])
                    fk2 = float(ds.variables['planck_fk2'][:])
                    bc1 = float(ds.variables['planck_bc1'][:])
                    bc2 = float(ds.variables['planck_bc2'][:])
                    brightness_temp = _rad_to_brightness_temp(rad, fk1, fk2, bc1, bc2)
                except Exception:
                    brightness_temp = rad

                try:
                    scan_start_time = str(ds.time_coverage_start)
                except Exception:
                    scan_start_time = 'unknown'

                try:
                    proj         = ds.variables['goes_imager_projection']
                    sat_height_m = float(proj.perspective_point_height)
                    sat_lon      = float(proj.longitude_of_projection_origin)
                except Exception:
                    sat_height_m = 35_786_023.0

                ds.close()

                flat_x   = xx.ravel()
                flat_y   = yy.ravel()
                flat_rad = brightness_temp.ravel()

                valid_mask = np.isfinite(flat_rad)
                flat_x   = flat_x[valid_mask]
                flat_y   = flat_y[valid_mask]
                flat_rad = flat_rad[valid_mask]

                if len(flat_x) > MAX_RASTER_POINTS:
                    rng     = np.random.RandomState(42)
                    indices = rng.choice(len(flat_x), MAX_RASTER_POINTS, replace=False)
                    flat_x   = flat_x[indices]
                    flat_y   = flat_y[indices]
                    flat_rad = flat_rad[indices]

                lat_deg, lon_deg = _goes_fixedgrid_to_latlon(
                    flat_x, flat_y,
                    sat_height_m=sat_height_m,
                    sat_lon_deg=sat_lon,
                )

                valid2   = np.isfinite(lat_deg) & np.isfinite(lon_deg)
                lat_deg  = lat_deg[valid2]
                lon_deg  = lon_deg[valid2]
                flat_rad = flat_rad[valid2]

                min_lon, min_lat, max_lon, max_lat = aoi
                aoi_mask = (
                    (lat_deg >= min_lat) & (lat_deg <= max_lat)
                    & (lon_deg >= min_lon) & (lon_deg <= max_lon)
                )
                lat_deg  = lat_deg[aoi_mask]
                lon_deg  = lon_deg[aoi_mask]
                flat_rad = flat_rad[aoi_mask]

                if len(lat_deg) == 0:
                    logger.info(f"NOAA GOES: {filename} has no data in AOI")
                    continue

                df = pd.DataFrame({
                    'lat':             lat_deg,
                    'lon':             lon_deg,
                    'raster_value':    flat_rad,
                    'source_file':     filename,
                    'source_format':   'noaa_goes',
                    'band':            band,
                    'scan_start_time': scan_start_time,
                })

                register_loaded_file(local_path, 'noaa_goes', len(df))
                all_dfs.append(df)
                logger.info(f"NOAA GOES: {len(df)} pixels in AOI from {filename}")

            except Exception as exc:
                logger.warning(f"NOAA GOES: failed to process {filename}: {exc}")
                continue

        if not all_dfs:
            return empty_fetcher_df(['band', 'scan_start_time'])

        result = pd.concat(all_dfs, ignore_index=True)
        result = validate_fetcher_output(result, 'NOAAGOES')
        logger.info(f"NOAA GOES: {len(result)} total point features returned")
        return result

    except ImportError as exc:
        logger.warning(f"NOAA GOES: missing dependency – {exc}; returning empty DataFrame")
        return empty_fetcher_df(['band', 'scan_start_time'])
    except Exception as exc:
        logger.warning(f"NOAA GOES fetcher unhandled exception: {exc}")
        return empty_fetcher_df(['band', 'scan_start_time'])
