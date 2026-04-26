"""
Contract ingestion for GEO-PR-INT.

Priority order:
  1. Contract_Sweeper pr_contracts_master.csv (preferred — already normalized)
  2. Contract_Sweeper pr_all_awards_master.csv (unified multi-dataset)
  3. USASpending API live query (fallback when no local CSV exists)

Output schema (all paths produce the same columns):
  award_id, recipient_name, recipient_name_norm, description,
  obligated_amount, award_date, fiscal_year,
  place_of_performance_city, place_of_performance_state,
  awarding_agency_name, naics_code, psc_code,
  lat, lon, geocode_method,
  matched_keywords (list)
"""

import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from config import CONTRACT_MASTER_PATH, UNIFIED_AWARDS_PATH, SETTINGS
from utils.geo_helpers import PR_MUNICIPALITY_CENTROIDS, PR_CENTROID, geocode_place_name

logger = logging.getLogger(__name__)

USASPENDING_API = SETTINGS["usaspending"]["api_base"]
KEYWORDS = SETTINGS["usaspending"]["keywords"]

# Columns we need from Contract_Sweeper's normalized output
_CS_COLUMN_MAP = {
    # Contract_Sweeper canonical → our canonical
    "contract_id":          "award_id",
    "award_id":             "award_id",
    "vendor_name":          "recipient_name",
    "recipient_name":       "recipient_name",
    "description":          "description",
    "obligated_amount":     "obligated_amount",
    "award_amount":         "obligated_amount",
    "award_date":           "award_date",
    "fiscal_year":          "fiscal_year",
    "pop_city":             "place_of_performance_city",
    "place_of_performance_city": "place_of_performance_city",
    "pop_state":            "place_of_performance_state",
    "awarding_agency":      "awarding_agency_name",
    "awarding_agency_name": "awarding_agency_name",
    "naics_code":           "naics_code",
    "psc_code":             "psc_code",
}

OUTPUT_COLS = [
    "award_id", "recipient_name", "recipient_name_norm", "description",
    "obligated_amount", "award_date", "fiscal_year",
    "place_of_performance_city", "place_of_performance_state",
    "awarding_agency_name", "naics_code", "psc_code",
    "lat", "lon", "geocode_method", "matched_keywords",
]


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remap Contract_Sweeper columns to our canonical schema."""
    rename = {}
    for col in df.columns:
        lc = col.lower().strip()
        if lc in _CS_COLUMN_MAP:
            rename[col] = _CS_COLUMN_MAP[lc]
    return df.rename(columns=rename)


def _geocode_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add lat/lon to contracts using place-of-performance city lookup."""
    df = df.copy()
    lats, lons, methods = [], [], []
    pop_col = "place_of_performance_city" if "place_of_performance_city" in df.columns else None
    for _, row in df.iterrows():
        coords = None
        method = "pr_centroid"
        if pop_col:
            city = str(row.get(pop_col, ""))
            coords = geocode_place_name(city)
            if coords:
                method = "municipality_lookup"
        if coords is None:
            coords = PR_CENTROID
        lats.append(coords[0])
        lons.append(coords[1])
        methods.append(method)
    df["lat"] = lats
    df["lon"] = lons
    df["geocode_method"] = methods
    return df


def _match_keywords(df: pd.DataFrame) -> pd.DataFrame:
    """Add matched_keywords column based on contract description."""
    df = df.copy()
    if "description" not in df.columns:
        df["matched_keywords"] = [[] for _ in range(len(df))]
        return df

    def _find_keywords(text):
        if not isinstance(text, str):
            return []
        low = text.lower()
        return [kw for kw in KEYWORDS if kw.lower() in low]

    df["matched_keywords"] = df["description"].apply(_find_keywords)
    return df


def _normalise_names(df: pd.DataFrame) -> pd.DataFrame:
    """Add recipient_name_norm (lowercase, strip legal suffixes)."""
    import re
    _SUFFIXES = re.compile(
        r"\b(llc|inc|corp|corporation|company|co|ltd|lp|llp|associates|group"
        r"|solutions|services|contractors|construction|consulting)\b\.?",
        re.IGNORECASE,
    )
    df = df.copy()
    if "recipient_name" in df.columns:
        df["recipient_name_norm"] = (
            df["recipient_name"]
            .fillna("")
            .str.lower()
            .str.strip()
            .apply(lambda n: _SUFFIXES.sub("", n).strip().strip(",").strip())
        )
    else:
        df["recipient_name_norm"] = ""
    return df


def _ensure_output_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee all OUTPUT_COLS exist (fill missing with sensible defaults)."""
    df = df.copy()
    defaults = {
        "award_id": "",
        "recipient_name": "",
        "recipient_name_norm": "",
        "description": "",
        "obligated_amount": 0.0,
        "award_date": "",
        "fiscal_year": 0,
        "place_of_performance_city": "",
        "place_of_performance_state": "PR",
        "awarding_agency_name": "",
        "naics_code": "",
        "psc_code": "",
        "lat": PR_CENTROID[0],
        "lon": PR_CENTROID[1],
        "geocode_method": "pr_centroid",
        "matched_keywords": None,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
    if df["matched_keywords"].dtype == object:
        df["matched_keywords"] = df["matched_keywords"].apply(
            lambda v: v if isinstance(v, list) else []
        )
    return df[OUTPUT_COLS]


# ── Path 1: Contract_Sweeper CSV ──────────────────────────────────────────────

def load_from_contract_sweeper(path: Path | None = None) -> pd.DataFrame:
    """Load contracts from Contract_Sweeper's normalized master CSV."""
    candidates = [
        path,
        CONTRACT_MASTER_PATH,
        UNIFIED_AWARDS_PATH,
    ]
    for p in candidates:
        if p is None:
            continue
        if not Path(p).exists():
            logger.debug(f"Contract CSV not found: {p}")
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
            logger.info(f"Loaded {len(df)} contract rows from {p}")
            df = _normalise_columns(df)
            df = _normalise_names(df)
            df = _geocode_dataframe(df)
            df = _match_keywords(df)
            df = _ensure_output_cols(df)
            logger.info(
                f"Contract ingestion (file): {len(df)} rows, "
                f"{(df['matched_keywords'].apply(len) > 0).sum()} keyword matches"
            )
            return df
        except Exception as exc:
            logger.warning(f"Failed to load contract CSV {p}: {exc}")

    return pd.DataFrame(columns=OUTPUT_COLS)


# ── Path 2: USASpending live API ──────────────────────────────────────────────

def _usaspending_page(keyword: str, page: int, page_size: int) -> list[dict]:
    """Fetch one page of USASpending awards for a keyword, filtered to PR."""
    url = f"{USASPENDING_API}/search/spending_by_award/"
    payload = {
        "filters": {
            "place_of_performance_locations": [
                {"country": "USA", "state": "PR"}
            ],
            "award_type_codes": ["A", "B", "C", "D"],
            "keywords": [keyword],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Start Date", "Description",
            "Place of Performance City Name",
            "Place of Performance State Code",
            "Awarding Agency Name",
            "NAICS Code", "PSC Code",
        ],
        "page": page,
        "limit": page_size,
        "sort": "Award Amount",
        "order": "desc",
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as exc:
        logger.debug(f"USASpending page failed (kw={keyword}, p={page}): {exc}")
        return []


def _usaspending_row_to_dict(row: dict) -> dict:
    return {
        "award_id":                    row.get("Award ID", ""),
        "recipient_name":              row.get("Recipient Name", ""),
        "description":                 row.get("Description", ""),
        "obligated_amount":            float(row.get("Award Amount") or 0),
        "award_date":                  row.get("Start Date", ""),
        "fiscal_year":                 0,
        "place_of_performance_city":   row.get("Place of Performance City Name", ""),
        "place_of_performance_state":  row.get("Place of Performance State Code", "PR"),
        "awarding_agency_name":        row.get("Awarding Agency Name", ""),
        "naics_code":                  str(row.get("NAICS Code", "") or ""),
        "psc_code":                    str(row.get("PSC Code", "") or ""),
    }


def load_from_usaspending_api(max_pages: int | None = None) -> pd.DataFrame:
    """Live-query USASpending for PR infrastructure contracts."""
    cfg = SETTINGS["usaspending"]
    if max_pages is None:
        max_pages = cfg.get("max_pages", 10)
    page_size = cfg.get("page_size", 100)

    all_rows: list[dict] = []
    seen_ids: set = set()

    for kw in KEYWORDS[:5]:   # top-5 keywords to keep call count reasonable
        for page in range(1, max_pages + 1):
            rows = _usaspending_page(kw, page, page_size)
            if not rows:
                break
            for r in rows:
                d = _usaspending_row_to_dict(r)
                if d["award_id"] not in seen_ids:
                    seen_ids.add(d["award_id"])
                    all_rows.append(d)
            if len(rows) < page_size:
                break
            time.sleep(0.2)   # polite rate-limiting

    if not all_rows:
        logger.warning("USASpending API returned no rows")
        return pd.DataFrame(columns=OUTPUT_COLS)

    df = pd.DataFrame(all_rows)
    df = _normalise_names(df)
    df = _geocode_dataframe(df)
    df = _match_keywords(df)
    df = _ensure_output_cols(df)
    logger.info(
        f"Contract ingestion (API): {len(df)} rows, "
        f"{(df['matched_keywords'].apply(len) > 0).sum()} keyword matches"
    )
    return df


# ── Public entry point ────────────────────────────────────────────────────────

def load_contracts(force_api: bool = False) -> pd.DataFrame:
    """Load contracts, preferring local Contract_Sweeper CSV over live API.

    Parameters
    ----------
    force_api : if True, skip local files and query USASpending directly

    Returns
    -------
    DataFrame with OUTPUT_COLS columns.
    """
    if not force_api:
        df = load_from_contract_sweeper()
        if len(df) > 0:
            return df
        logger.info("No local contract files found — falling back to USASpending API")

    return load_from_usaspending_api()
