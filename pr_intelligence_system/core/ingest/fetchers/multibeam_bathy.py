"""
NOAA Multibeam Bathymetry Fetcher
===================================
Loads processed multibeam sonar data from the PR EEZ survey (cruise PD18PR04,
EM124 Kongsberg system).  Covers the full Puerto Rico EEZ including the PR Trench
(~0–8 400 m).

Copy your iCloud data folder to the project before running:

    cp -r ~/Library/Mobile\\ Documents/com~apple~CloudDocs/<multibeam-folder>/ \\
           pr_intelligence_system/data/raw/multibeam/

Expected directory layout after copy:

    data/raw/multibeam/
        products/
            PRT_01132019_final.tif.gz   ← primary (processed GeoTIFF grid)
            PRT_*_Cube.xyz.gz           ← secondary (XYZ point cloud)
            PRT_01132019.bag.gz         ← unused here (GDAL can read BAG natively)
        em124/
            *.mb121.gz                  ← tertiary (raw GSF via mblist subprocess)

Processing priority:
  1. CSV sounding cache (fast subsequent runs)
  2. Processed GeoTIFF  (*.tif / *.tif.gz  in products/)
  3. XYZ point cloud    (*.xyz / *.xyz.gz   in products/)
  4. Raw MB-System files via mblist subprocess
  5. Graceful empty return

Depth convention: raster_value is negative below sea level (matches bathymetry_proxy).
Output schema: lat, lon, raster_value, source_file, source_format, acquisition_date.
"""

import gzip
import logging
import os
import shutil
import subprocess
import tempfile

import numpy as np
import pandas as pd

from config.fetcher_config import DEFAULT_AOI, FETCHER_CACHE_ROOT
from core.ingest.fetchers.base import empty_fetcher_df, validate_fetcher_output

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_RAW_DIR = os.path.dirname(FETCHER_CACHE_ROOT)  # data/raw/

_EXCLUDE_DIRS = {'fetcher_cache', 'multibeam'}


def _find_mb_files(data_dir: str, max_files: int = 5) -> list:
    """Recursively walk data_dir and return up to max_files MB-System file paths."""
    found = []
    for root, dirs, files in os.walk(data_dir):
        # Skip hidden dirs only — do NOT exclude 'multibeam' here because that
        # name legitimately appears as a subdirectory within cruise folders
        # (e.g. atlantis/AT29-04/multibeam/data/version1/MB/em122/).
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for fname in sorted(files):
            if '.mb' in fname.lower() and not fname.startswith('.'):
                found.append(os.path.join(root, fname))
                if len(found) >= max_files:
                    return found
    return found


def _discover_data_dir() -> str:
    """Return the first data/raw/ subdirectory that looks like a multibeam mission folder.

    Accepts any folder name (e.g. 'atlantis', 'PD18PR04').  Checks for:
      - a products/ child containing GeoTIFF/XYZ files, OR
      - any *.mb* file anywhere within the directory tree.
    Falls back to data/raw/multibeam/ if nothing matches.
    """
    fallback = os.path.join(_RAW_DIR, 'multibeam')
    if not os.path.isdir(_RAW_DIR):
        return fallback
    try:
        for entry in sorted(os.scandir(_RAW_DIR), key=lambda e: e.name):
            if not entry.is_dir() or entry.name in _EXCLUDE_DIRS:
                continue
            if os.path.isdir(os.path.join(entry.path, 'products')):
                return entry.path
            if _find_mb_files(entry.path, max_files=1):
                return entry.path
    except OSError:
        pass
    return fallback


MULTIBEAM_DATA_DIR = _discover_data_dir()  # best-effort at import time; re-resolved at call time
SOUNDING_CACHE = os.path.join(FETCHER_CACHE_ROOT, 'multibeam', 'soundings_cache.csv')

MAX_SOUNDINGS = 50_000  # subsample cap for pipeline tractability

# ── Module-level cache (populated once per process) ────────────────────────────
_BATHY_CACHE: pd.DataFrame = None


def get_cached_bathy() -> pd.DataFrame:
    """Return the most recently loaded bathymetry DataFrame, or None."""
    return _BATHY_CACHE


# ── Check mblist availability once at import ───────────────────────────────────
def _mblist_available() -> bool:
    try:
        r = subprocess.run(['mblist', '--version'], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


_MBLIST_OK = _mblist_available()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _gunzip_to_temp(gz_path: str, suffix: str) -> str:
    """Decompress a .gz file to a named temp file; caller is responsible for cleanup."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    with gzip.open(gz_path, 'rb') as f_in, open(tmp.name, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    return tmp.name


def _aoi_filter(df: pd.DataFrame, aoi: tuple) -> pd.DataFrame:
    min_lon, min_lat, max_lon, max_lat = aoi
    return df[
        (df['lon'] >= min_lon) & (df['lon'] <= max_lon) &
        (df['lat'] >= min_lat) & (df['lat'] <= max_lat)
    ].reset_index(drop=True)


def _subsample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    rng = np.random.RandomState(42)
    idx = rng.choice(len(df), size=max_points, replace=False)
    return df.iloc[idx].reset_index(drop=True)


def _ensure_negative_depth(df: pd.DataFrame) -> pd.DataFrame:
    """Flip sign if values are positive (depth-positive convention → negative)."""
    if df['raster_value'].median() > 0:
        df = df.copy()
        df['raster_value'] = -df['raster_value']
    return df


# ── Loader: processed GeoTIFF ──────────────────────────────────────────────────

def _load_geotiff(tif_path: str, aoi: tuple, max_points: int,
                  source_file: str) -> pd.DataFrame:
    from core.ingest.loaders.raster_loader import load_raster
    df = load_raster(tif_path)
    if df is None or len(df) == 0:
        return pd.DataFrame()
    df = df.rename(columns={'raster_value': 'raster_value'})
    df = _ensure_negative_depth(df)
    df = df[df['raster_value'] < 0]  # keep underwater soundings only
    df = _aoi_filter(df, aoi)
    df = _subsample(df, max_points)
    df['source_file']      = source_file
    df['source_format']    = 'multibeam_bathy'
    df['acquisition_date'] = '2019-01-13'  # PD18PR04 cruise completion date
    return df[['lat', 'lon', 'raster_value', 'source_file',
               'source_format', 'acquisition_date']]


# ── Loader: XYZ point cloud ────────────────────────────────────────────────────

def _load_xyz(xyz_path: str, aoi: tuple, max_points: int,
              source_file: str) -> pd.DataFrame:
    """Parse NOAA XYZ cube: lon lat depth (space-separated, depth positive-down)."""
    chunks = []
    try:
        for chunk in pd.read_csv(
            xyz_path, sep=r'\s+', header=None,
            names=['lon', 'lat', 'depth'],
            chunksize=200_000, comment='#',
        ):
            chunk = chunk.dropna()
            chunk['raster_value'] = -chunk['depth'].abs()  # ensure negative
            chunks.append(chunk[['lat', 'lon', 'raster_value']])
    except Exception as exc:
        logger.warning(f"XYZ parse error ({xyz_path}): {exc}")
        return pd.DataFrame()

    if not chunks:
        return pd.DataFrame()

    df = pd.concat(chunks, ignore_index=True)
    df = _aoi_filter(df, aoi)
    df = _subsample(df, max_points)
    df['source_file']      = source_file
    df['source_format']    = 'multibeam_bathy'
    df['acquisition_date'] = '2019-01-13'
    return df[['lat', 'lon', 'raster_value', 'source_file',
               'source_format', 'acquisition_date']]


# ── Loader: raw MB-System via mblist ──────────────────────────────────────────

def _load_mblist(mb_path: str, aoi: tuple, source_file: str) -> pd.DataFrame:
    """Run mblist -O XYZ on a single MB-System file; parse stdout."""
    try:
        result = subprocess.run(
            ['mblist', '-I', mb_path, '-O', 'XYZ', '-N'],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return pd.DataFrame()

        from io import StringIO
        df = pd.read_csv(
            StringIO(result.stdout), sep=r'\s+', header=None,
            names=['lon', 'lat', 'depth'],
        )
        df = df.dropna()
        df['raster_value'] = -df['depth'].abs()
        df = df[['lat', 'lon', 'raster_value']]
        df = _aoi_filter(df, aoi)
        df['source_file']      = source_file
        df['source_format']    = 'multibeam_bathy'
        df['acquisition_date'] = _date_from_filename(source_file)
        return df[['lat', 'lon', 'raster_value', 'source_file',
                   'source_format', 'acquisition_date']]

    except Exception as exc:
        logger.debug(f"mblist failed on {mb_path}: {exc}")
        return pd.DataFrame()


# ── Loader: Kongsberg .all via pyall (pure Python, no MB-System needed) ────────

def _load_pyall_file(all_path: str) -> pd.DataFrame:
    """Extract lat/lon/depth from a Kongsberg .all file using the pyall library.

    Walks datagrams sequentially: tracks the last known position (P datagram)
    and emits a sounding at that position for each depth ping (D/X datagram).
    Returns a DataFrame with lat, lon, raster_value (negative metres).
    """
    import pyall  # pip install pyall

    reader = pyall.ALLReader(all_path)
    rows = []
    cur_lat = cur_lon = None

    while reader.moreData():
        typechar, dg = reader.readDatagram()

        if typechar == 'P':
            dg.read()
            cur_lat = getattr(dg, 'Latitude',  getattr(dg, 'latitude',  None))
            cur_lon = getattr(dg, 'Longitude', getattr(dg, 'longitude', None))

        elif typechar in ('D', 'X') and cur_lat is not None:
            dg.read()
            raw = (
                getattr(dg, 'depth',  None)
                or getattr(dg, 'depths', None)
                or getattr(dg, 'z',     None)
            )
            if raw:
                valid = [abs(v) for v in raw if v and not np.isnan(float(v))]
                if valid:
                    rows.append({
                        'lat':          cur_lat,
                        'lon':          cur_lon,
                        'raster_value': -float(np.median(valid)),
                    })

    try:
        reader.close()
    except Exception:
        pass

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _load_pyall(all_path: str, aoi: tuple, source_file: str) -> pd.DataFrame:
    """Wrapper: gunzip if needed, call _load_pyall_file, apply AOI filter."""
    try:
        df = _load_pyall_file(all_path)
        if df.empty:
            return df
        df = df[df['raster_value'] < 0]
        df = _aoi_filter(df, aoi)
        df['source_file']      = source_file
        df['source_format']    = 'multibeam_bathy'
        df['acquisition_date'] = _date_from_filename(source_file)
        return df[['lat', 'lon', 'raster_value', 'source_file',
                   'source_format', 'acquisition_date']]
    except ImportError:
        logger.warning("[multibeam_bathy] pyall not installed — run: pip install pyall")
        return pd.DataFrame()
    except Exception as exc:
        logger.debug(f"pyall failed on {all_path}: {exc}")
        return pd.DataFrame()
        df['source_file']      = source_file
        df['source_format']    = 'multibeam_bathy'
        df['acquisition_date'] = _date_from_filename(source_file)
        return df

    except Exception as exc:
        logger.debug(f"mblist failed on {mb_path}: {exc}")
        return pd.DataFrame()


def _date_from_filename(name: str) -> str:
    """Best-effort date extraction from NOAA MB filenames like 0044_20181205_..."""
    import re
    m = re.search(r'(\d{8})', os.path.basename(name))
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return '2018-12-01'


# ── Main fetcher ───────────────────────────────────────────────────────────────

def fetch_multibeam_bathy(
    data_dir: str = None,
    aoi: tuple = DEFAULT_AOI,
    max_points: int = MAX_SOUNDINGS,
) -> pd.DataFrame:
    """Load NOAA multibeam bathymetry for the PR EEZ.

    Returns a DataFrame with columns:
        lat, lon, raster_value (negative metres), source_file,
        source_format, acquisition_date
    """
    global _BATHY_CACHE

    if data_dir is None:
        data_dir = _discover_data_dir()

    empty = empty_fetcher_df(extra_cols=['acquisition_date'])

    # ── 1. CSV sounding cache ──────────────────────────────────────────────────
    if os.path.exists(SOUNDING_CACHE):
        try:
            df = pd.read_csv(SOUNDING_CACHE)
            if len(df) > 0 and 'raster_value' in df.columns:
                logger.info(
                    f"[multibeam_bathy] cache hit: {len(df)} soundings "
                    f"from {SOUNDING_CACHE}"
                )
                _BATHY_CACHE = df.copy()
                return df
        except Exception as exc:
            logger.debug(f"[multibeam_bathy] cache read failed: {exc}")

    if not os.path.isdir(data_dir):
        logger.warning(
            "[multibeam_bathy] data directory not found. "
            "Copy your NOAA multibeam files to: "
            f"{data_dir}\n"
            "  cp -r ~/Library/Mobile\\ Documents/com~apple~CloudDocs/<folder>/ "
            f"{data_dir}/"
        )
        return empty

    frames: list[pd.DataFrame] = []
    tmp_files: list[str] = []

    try:
        # ── 2. Processed GeoTIFF ───────────────────────────────────────────────
        products_dir = os.path.join(data_dir, 'products')
        if os.path.isdir(products_dir):
            for fname in sorted(os.listdir(products_dir)):
                fpath = os.path.join(products_dir, fname)
                lower = fname.lower()

                if lower.endswith('.tif.gz') and 'backscatter' not in lower and 'uncertainty' not in lower:
                    logger.info(f"[multibeam_bathy] loading GeoTIFF: {fname}")
                    tmp = _gunzip_to_temp(fpath, '.tif')
                    tmp_files.append(tmp)
                    df = _load_geotiff(tmp, aoi, max_points, fname)
                    if len(df) > 0:
                        frames.append(df)
                        break  # one gridded product is sufficient

                elif lower.endswith('.tif') and 'backscatter' not in lower and 'uncertainty' not in lower:
                    logger.info(f"[multibeam_bathy] loading GeoTIFF: {fname}")
                    df = _load_geotiff(fpath, aoi, max_points, fname)
                    if len(df) > 0:
                        frames.append(df)
                        break

        # ── 3. XYZ point cloud (if no GeoTIFF succeeded) ─────────────────────
        if not frames and os.path.isdir(products_dir):
            for fname in sorted(os.listdir(products_dir)):
                fpath = os.path.join(products_dir, fname)
                lower = fname.lower()

                if lower.endswith('.xyz.gz'):
                    logger.info(f"[multibeam_bathy] loading XYZ: {fname}")
                    tmp = _gunzip_to_temp(fpath, '.xyz')
                    tmp_files.append(tmp)
                    df = _load_xyz(tmp, aoi, max_points, fname)
                    if len(df) > 0:
                        frames.append(df)
                        break

                elif lower.endswith('.xyz'):
                    logger.info(f"[multibeam_bathy] loading XYZ: {fname}")
                    df = _load_xyz(fpath, aoi, max_points, fname)
                    if len(df) > 0:
                        frames.append(df)
                        break

        # ── 4. Raw MB-System files via mblist ─────────────────────────────────
        if not frames and _MBLIST_OK:
            mb_file_paths = _find_mb_files(data_dir, max_files=5)

            for fpath in mb_file_paths:
                fname = os.path.basename(fpath)
                lower = fname.lower()
                work_path = fpath

                if lower.endswith('.gz'):
                    suffix = '.' + lower[:-3].split('.')[-1]
                    tmp = _gunzip_to_temp(fpath, suffix)
                    tmp_files.append(tmp)
                    work_path = tmp

                logger.info(f"[multibeam_bathy] mblist: {fname}")
                df = _load_mblist(work_path, aoi, fname)
                if len(df) > 0:
                    frames.append(df)

        # ── 5. pyall fallback (pure Python, no MB-System required) ──────────
        if not frames and not _MBLIST_OK:
            mb_file_paths = _find_mb_files(data_dir, max_files=5)
            if mb_file_paths:
                logger.info(
                    f"[multibeam_bathy] mblist not found; trying pyall on "
                    f"{len(mb_file_paths)} file(s) — install: pip install pyall"
                )
                for fpath in mb_file_paths:
                    fname = os.path.basename(fpath)
                    lower = fname.lower()
                    work_path = fpath

                    if lower.endswith('.gz'):
                        suffix = '.' + lower[:-3].split('.')[-1]
                        tmp = _gunzip_to_temp(fpath, suffix)
                        tmp_files.append(tmp)
                        work_path = tmp

                    df = _load_pyall(work_path, aoi, fname)
                    if len(df) > 0:
                        frames.append(df)
            else:
                logger.warning(
                    "[multibeam_bathy] no MB files found and mblist unavailable. "
                    "Install pyall (pip install pyall) or MB-System (conda install "
                    "-c conda-forge mbsystem) to process raw .all files."
                )

    finally:
        for tmp in tmp_files:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if not frames:
        logger.warning("[multibeam_bathy] no bathymetry data loaded")
        return empty

    result = pd.concat(frames, ignore_index=True)
    result = _subsample(result, max_points)  # final cap across all sources

    # Write CSV sounding cache
    os.makedirs(os.path.dirname(SOUNDING_CACHE), exist_ok=True)
    result.to_csv(SOUNDING_CACHE, index=False)
    logger.info(
        f"[multibeam_bathy] {len(result)} soundings loaded; "
        f"cache written to {SOUNDING_CACHE}"
    )

    _BATHY_CACHE = result.copy()
    validate_fetcher_output(result, 'multibeam_bathy')
    return result
