"""
Shared base utilities for all contract source fetchers.
"""

import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

from config import GEO_PR_INT_ROOT, SETTINGS
from ingestion.contracts.loader import (
    OUTPUT_COLS, SOURCE_GROUP_WEIGHTS, DEFAULT_SOURCE_WEIGHT,
    _normalise_names, _geocode_dataframe, _match_keywords,
    _ensure_output_cols, _assign_source_group_weights,
)

logger = logging.getLogger(__name__)

_CACHE_ROOT = GEO_PR_INT_ROOT / "data" / "cache" / "contracts"
_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "GEO-PR-INT/1.0 (geospatial research; non-commercial)",
    "Accept": "application/json, text/html, */*",
}


def cache_path(source_group: str) -> Path:
    return _CACHE_ROOT / f"{source_group.lower()}.csv"


def load_cache(source_group: str) -> pd.DataFrame | None:
    p = cache_path(source_group)
    if p.exists():
        try:
            df = pd.read_csv(p, low_memory=False)
            logger.info(f"{source_group}: loaded {len(df)} rows from cache")
            return df
        except Exception as exc:
            logger.warning(f"{source_group}: cache read failed: {exc}")
    return None


def save_cache(df: pd.DataFrame, source_group: str) -> None:
    p = cache_path(source_group)
    try:
        df.to_csv(p, index=False)
        logger.info(f"{source_group}: {len(df)} rows written to cache")
    except Exception as exc:
        logger.warning(f"{source_group}: cache write failed: {exc}")


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def safe_get(url: str, session: requests.Session | None = None,
             timeout: int = 30, params: dict | None = None) -> requests.Response | None:
    """GET with retry on transient errors. Returns None on permanent failure."""
    sess = session or get_session()
    for attempt in range(3):
        try:
            resp = sess.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.debug(f"Rate-limited; waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                logger.warning(f"GET {url} → 403 Forbidden (may need API key or credentials)")
                return None
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"GET {url} timed out (attempt {attempt+1})")
        except Exception as exc:
            logger.debug(f"GET {url} failed: {exc}")
            break
    return None


def safe_post(url: str, payload: dict, session: requests.Session | None = None,
              timeout: int = 30) -> requests.Response | None:
    """POST with retry on transient errors."""
    sess = session or get_session()
    for attempt in range(3):
        try:
            resp = sess.post(url, json=payload, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                logger.warning(f"POST {url} → 403 Forbidden")
                return None
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"POST {url} timed out (attempt {attempt+1})")
        except Exception as exc:
            logger.debug(f"POST {url} failed: {exc}")
            break
    return None


def finalise(df: pd.DataFrame, source_group: str) -> pd.DataFrame:
    """Apply standard pipeline: normalise names → assign source group → geocode → keywords → ensure cols."""
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)
    df["source_group"] = source_group
    df = _normalise_names(df)
    df = _assign_source_group_weights(df)
    df = _geocode_dataframe(df)
    df = _match_keywords(df)
    df = _ensure_output_cols(df)
    return df


def empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLS)
