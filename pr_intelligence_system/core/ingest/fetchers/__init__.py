"""
core.ingest.fetchers
====================
Public satellite data fetcher package.

Each fetcher is a self-contained module that pulls data from a public
(no-credentials) source, converts it to the canonical DataFrame schema
(lat, lon, raster_value, source_file, source_format), and returns it
ready for unify_dataframes().

All fetchers degrade gracefully: on any failure they log a WARNING and
return an empty DataFrame — the pipeline is never interrupted.

Quick usage
-----------
    from core.ingest.fetchers import run_all_fetchers
    dfs = run_all_fetchers()          # returns list of DataFrames

    # Or call individual fetchers:
    from core.ingest.fetchers import fetch_viirs_firms
    df = fetch_viirs_firms(aoi=(-67.5, 17.8, -65.0, 18.6))
"""

import logging
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, DEFAULT_DATE_RANGE

from .sentinel1_sar     import fetch_sentinel1_sar
from .sentinel2_optical import fetch_sentinel2_optical
from .copernicus_dem    import fetch_copernicus_dem
from .viirs_firms       import fetch_viirs_firms
from .noaa_goes         import fetch_noaa_goes
from .noaa_oisst        import fetch_noaa_oisst
from .landsat_c2        import fetch_landsat_c2
from .chirps_precip     import fetch_chirps_precip
from .multibeam_bathy   import fetch_multibeam_bathy

logger = logging.getLogger(__name__)

__all__ = [
    'fetch_sentinel1_sar',
    'fetch_sentinel2_optical',
    'fetch_copernicus_dem',
    'fetch_viirs_firms',
    'fetch_noaa_goes',
    'fetch_noaa_oisst',
    'fetch_landsat_c2',
    'fetch_chirps_precip',
    'fetch_multibeam_bathy',
    'run_all_fetchers',
]


def run_all_fetchers(
    aoi: tuple = DEFAULT_AOI,
    date_range: tuple = DEFAULT_DATE_RANGE,
) -> list:
    """Run all nine satellite/climate fetchers and return a list of DataFrames.

    Fetchers execute independently — a failure in one does not affect the
    others.  Empty DataFrames are included in the returned list; callers
    should filter with ``len(df) > 0`` as needed.

    Parameters
    ----------
    aoi        : (min_lon, min_lat, max_lon, max_lat) bounding box in WGS-84
    date_range : (start_date, end_date) strings — format depends on fetcher
                 ('YYYY-MM-DD' for FIRMS, 'YYYYMMDD' for Sentinel)

    Returns
    -------
    list of pd.DataFrame, one per fetcher (may be empty)
    """
    from .base import empty_fetcher_df

    # Sentinel date strings should be 'YYYYMMDD'
    s1_s2_date = (
        date_range[0].replace('-', ''),
        date_range[1].replace('-', ''),
    )

    fetchers = [
        ('Copernicus DEM GLO-30',      lambda: fetch_copernicus_dem(aoi=aoi)),
        ('Sentinel-1 SAR',             lambda: fetch_sentinel1_sar(aoi=aoi, date_range=s1_s2_date)),
        ('Sentinel-2 Optical',         lambda: fetch_sentinel2_optical(aoi=aoi, date_range=s1_s2_date)),
        ('VIIRS/FIRMS',                lambda: fetch_viirs_firms(aoi=aoi, date_range=date_range)),
        ('NOAA GOES',                  lambda: fetch_noaa_goes(aoi=aoi)),
        ('NOAA OISST SST',             lambda: fetch_noaa_oisst(aoi=aoi, date_range=date_range)),
        ('Landsat C2 L2',              lambda: fetch_landsat_c2(aoi=aoi, date_range=date_range)),
        ('CHIRPS Precipitation',       lambda: fetch_chirps_precip(aoi=aoi, date_range=date_range)),
        ('NOAA Multibeam Bathymetry',  lambda: fetch_multibeam_bathy(aoi=aoi)),
    ]

    results = []
    for name, fn in fetchers:
        logger.info(f"[Fetcher] Starting: {name}")
        try:
            df = fn()
            n  = len(df)
            logger.info(f"[Fetcher] {name}: {n} row(s) returned")
        except Exception as exc:
            logger.warning(f"[Fetcher] {name}: unhandled exception → {exc}; returning empty")
            df = empty_fetcher_df()
        results.append(df)

    total = sum(len(df) for df in results)
    logger.info(f"[Fetchers] All complete: {total} total rows across {len(results)} sources")
    return results
