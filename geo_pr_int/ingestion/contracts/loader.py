"""
Contract ingestion for GEO-PR-INT.

Source priority order:
  1. CONTRACT_CSV_PATH env var (user override)
  2. data/raw/pr_all_awards_master.csv (local drop location)
  3. data/raw/pr_contracts_master.csv
  4. ~/Documents/GitHub/Contract-Sweeper/data/staging/processed/ (Mac dev path)
  5. Sibling Contract_Sweeper repo output (legacy path)
  6. USASpending API live query (network fallback)

Supported source_groups (from Contract_Sweeper unified output):
  OCE_PR               Puerto Rico Office of Contract Education
  COR3_PR              Central Office for Recovery, Reconstruction and Resiliency
  CONTRALOR_PR         Puerto Rico Controller / Comptroller
  OGPE_PR              Oficina de Gerencia y Presupuesto (Budget Office)
  USASPENDING_FEDERAL  Federal awards via USASpending.gov
  FSRS_SUBAWARDS       Federal Subaward Reporting System
  SAM_ENTITY_REGISTRY  System for Award Management — entity/contractor registry
  DCAA_CONTRACTOR_BASELINE  Defense Contract Audit Agency contractor baseline

Output schema (all paths produce the same columns):
  award_id, recipient_name, recipient_name_norm, description,
  obligated_amount, award_date, fiscal_year,
  place_of_performance_city, place_of_performance_state,
  awarding_agency_name, naics_code, psc_code,
  lat, lon, geocode_method, matched_keywords,
  source_group, source_group_weight
"""

import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from config import CONTRACT_MASTER_PATH, UNIFIED_AWARDS_PATH, SETTINGS, GEO_PR_INT_ROOT
from utils.geo_helpers import PR_MUNICIPALITY_CENTROIDS, PR_CENTROID, geocode_place_name

logger = logging.getLogger(__name__)

USASPENDING_API = SETTINGS["usaspending"]["api_base"]
KEYWORDS = SETTINGS["usaspending"]["keywords"]

# ── Source group registry ─────────────────────────────────────────────────────
# Weight reflects relevance to infrastructure detection in PR:
#   COR3 and CONTRALOR are highest (direct PR infra reconstruction contracts)
#   Federal subawards are high (actual construction companies doing the work)
#   Entity registry / auditor baseline are lower (reference data, not awards)
SOURCE_GROUP_WEIGHTS: dict[str, float] = {
    "COR3_PR":                  1.00,   # FEMA/COR3 — post-hurricane reconstruction
    "CONTRALOR_PR":             0.90,   # PR Controller — municipal infrastructure
    "OGPE_PR":                  0.85,   # PR Budget Office — capital projects
    "OCE_PR":                   0.80,   # PR contracts — local government
    "USASPENDING_FEDERAL":      0.75,   # Federal awards — broadest coverage
    "FSRS_SUBAWARDS":           0.95,   # Subawards — actual construction firms
    "SAM_ENTITY_REGISTRY":      0.40,   # Entity data — no award amounts
    "DCAA_CONTRACTOR_BASELINE": 0.50,   # DoD baseline — partial PR relevance
}
DEFAULT_SOURCE_WEIGHT = 0.60  # for rows without a source_group column

# ── Column mappings ───────────────────────────────────────────────────────────
_CS_COLUMN_MAP = {
    # Contract_Sweeper canonical → our canonical
    "contract_id":               "award_id",
    "award_id":                  "award_id",
    "vendor_name":               "recipient_name",
    "recipient_name":            "recipient_name",
    "contractor_name":           "recipient_name",
    "description":               "description",
    "project_description":       "description",
    "obligated_amount":          "obligated_amount",
    "award_amount":              "obligated_amount",
    "total_obligated_amount":    "obligated_amount",
    "amount":                    "obligated_amount",
    "award_date":                "award_date",
    "start_date":                "award_date",
    "contract_date":             "award_date",
    "fiscal_year":               "fiscal_year",
    "pop_city":                  "place_of_performance_city",
    "place_of_performance_city": "place_of_performance_city",
    "city":                      "place_of_performance_city",
    "municipality":              "place_of_performance_city",
    "pop_state":                 "place_of_performance_state",
    "awarding_agency":           "awarding_agency_name",
    "awarding_agency_name":      "awarding_agency_name",
    "agency":                    "awarding_agency_name",
    "naics_code":                "naics_code",
    "naics":                     "naics_code",
    "psc_code":                  "psc_code",
    "psc":                       "psc_code",
    "source_group":              "source_group",
    "data_source":               "source_group",
    "source":                    "source_group",
}

OUTPUT_COLS = [
    "award_id", "recipient_name", "recipient_name_norm", "description",
    "obligated_amount", "award_date", "fiscal_year",
    "place_of_performance_city", "place_of_performance_state",
    "awarding_agency_name", "naics_code", "psc_code",
    "lat", "lon", "geocode_method", "matched_keywords",
    "source_group", "source_group_weight",
]


# ── Column normalisation ──────────────────────────────────────────────────────

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remap Contract_Sweeper columns to our canonical schema."""
    rename = {}
    for col in df.columns:
        lc = col.lower().strip()
        if lc in _CS_COLUMN_MAP:
            rename[col] = _CS_COLUMN_MAP[lc]
    return df.rename(columns=rename)


def _assign_source_group_weights(df: pd.DataFrame) -> pd.DataFrame:
    """Add source_group_weight based on the source_group column."""
    df = df.copy()
    if "source_group" not in df.columns:
        df["source_group"] = "USASPENDING_FEDERAL"
    df["source_group"] = df["source_group"].fillna("USASPENDING_FEDERAL").str.upper().str.strip()
    df["source_group_weight"] = df["source_group"].map(SOURCE_GROUP_WEIGHTS).fillna(DEFAULT_SOURCE_WEIGHT)
    return df


def _geocode_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add lat/lon using place-of-performance city lookup."""
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
    """Add matched_keywords list from contract description."""
    df = df.copy()
    if "description" not in df.columns:
        df["matched_keywords"] = [[] for _ in range(len(df))]
        return df

    def _find(text):
        if not isinstance(text, str):
            return []
        low = text.lower()
        return [kw for kw in KEYWORDS if kw.lower() in low]

    df["matched_keywords"] = df["description"].apply(_find)
    return df


def _normalise_names(df: pd.DataFrame) -> pd.DataFrame:
    """Add recipient_name_norm (lowercase, strip legal suffixes)."""
    import re
    _SUFFIXES = re.compile(
        r"\b(llc|inc|corp|corporation|company|co|ltd|lp|llp|associates|group"
        r"|solutions|services|contractors|construction|consulting|international"
        r"|enterprises|technologies|systems|management|partners)\b\.?",
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
    """Guarantee all OUTPUT_COLS exist with sensible defaults."""
    df = df.copy()
    defaults = {
        "award_id":                    "",
        "recipient_name":              "",
        "recipient_name_norm":         "",
        "description":                 "",
        "obligated_amount":            0.0,
        "award_date":                  "",
        "fiscal_year":                 0,
        "place_of_performance_city":   "",
        "place_of_performance_state":  "PR",
        "awarding_agency_name":        "",
        "naics_code":                  "",
        "psc_code":                    "",
        "lat":                         PR_CENTROID[0],
        "lon":                         PR_CENTROID[1],
        "geocode_method":              "pr_centroid",
        "matched_keywords":            None,
        "source_group":                "USASPENDING_FEDERAL",
        "source_group_weight":         DEFAULT_SOURCE_WEIGHT,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
    df["matched_keywords"] = df["matched_keywords"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    df["obligated_amount"] = pd.to_numeric(df["obligated_amount"], errors="coerce").fillna(0.0)
    return df[OUTPUT_COLS]


# ── CSV path resolution ───────────────────────────────────────────────────────

def _candidate_paths() -> list[Path]:
    """Return ordered list of CSV paths to try."""
    paths: list[Path] = []

    # 1. Explicit env var override
    env_path = os.environ.get("CONTRACT_CSV_PATH", "")
    if env_path:
        paths.append(Path(env_path).expanduser())

    # 2. Local data/raw drop location (primary for server deployments)
    raw_dir = GEO_PR_INT_ROOT / "data" / "raw"
    paths += [
        raw_dir / "pr_all_awards_master.csv",
        raw_dir / "pr_contracts_master.csv",
    ]

    # 3. Mac developer path (Contract-Sweeper repo on local machine)
    mac_base = Path.home() / "Documents" / "GitHub" / "Contract-Sweeper" / "data" / "staging" / "processed"
    paths += [
        mac_base / "pr_all_awards_master.csv",
        mac_base / "pr_contracts_master.csv",
    ]

    # 4. Settings-configured sibling repo paths
    paths += [CONTRACT_MASTER_PATH, UNIFIED_AWARDS_PATH]

    return paths


# ── Path 1: Contract_Sweeper CSV ──────────────────────────────────────────────

def load_from_contract_sweeper(path: Path | None = None) -> pd.DataFrame:
    """Load contracts from Contract_Sweeper unified CSV (all 8 source groups)."""
    candidates = ([Path(path)] if path else []) + _candidate_paths()

    for p in candidates:
        if p is None:
            continue
        p = Path(p)
        if not p.exists():
            logger.debug(f"Contract CSV not found: {p}")
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
            logger.info(f"Loaded {len(df)} contract rows from {p}")
            df = _normalise_columns(df)
            df = _normalise_names(df)
            df = _assign_source_group_weights(df)
            df = _geocode_dataframe(df)
            df = _match_keywords(df)
            df = _ensure_output_cols(df)

            groups = df["source_group"].value_counts().to_dict()
            kw_matches = (df["matched_keywords"].apply(len) > 0).sum()
            logger.info(
                f"Contract ingestion (file): {len(df)} rows, "
                f"{kw_matches} keyword matches, "
                f"source groups: {groups}"
            )
            return df
        except Exception as exc:
            logger.warning(f"Failed to load contract CSV {p}: {exc}")

    return pd.DataFrame(columns=OUTPUT_COLS)


# ── Path 2: USASpending live API ──────────────────────────────────────────────

_USA_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "GEO-PR-INT/1.0 (geospatial research)",
}


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
        resp = requests.post(url, json=payload, headers=_USA_HEADERS, timeout=30)
        if resp.status_code == 403:
            logger.warning("USASpending API returned 403 — rate-limited or blocked; skipping")
            return []
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
        "source_group":                "USASPENDING_FEDERAL",
    }


def load_from_usaspending_api(max_pages: int | None = None) -> pd.DataFrame:
    """Live-query USASpending for PR infrastructure contracts."""
    cfg = SETTINGS["usaspending"]
    if max_pages is None:
        max_pages = cfg.get("max_pages", 10)
    page_size = cfg.get("page_size", 100)

    all_rows: list[dict] = []
    seen_ids: set = set()

    for kw in KEYWORDS[:5]:
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
            time.sleep(0.2)

    if not all_rows:
        logger.warning("USASpending API returned no rows")
        return pd.DataFrame(columns=OUTPUT_COLS)

    df = pd.DataFrame(all_rows)
    df = _normalise_names(df)
    df = _assign_source_group_weights(df)
    df = _geocode_dataframe(df)
    df = _match_keywords(df)
    df = _ensure_output_cols(df)
    logger.info(
        f"Contract ingestion (API): {len(df)} rows, "
        f"{(df['matched_keywords'].apply(len) > 0).sum()} keyword matches"
    )
    return df


# ── Native source fetchers aggregator ────────────────────────────────────────

def run_all_source_fetchers(use_cache: bool = True) -> pd.DataFrame:
    """Run all 8 native source fetchers and merge results.

    Each fetcher targets its own data portal and caches independently.
    Results are concatenated and deduplicated by award_id.
    """
    from ingestion.contracts.sources import ALL_FETCHERS

    frames: list[pd.DataFrame] = []
    for sg, fetch_fn in ALL_FETCHERS.items():
        try:
            df = fetch_fn(use_cache=use_cache)
            if not df.empty:
                logger.info(f"Source fetcher {sg}: {len(df)} rows")
                frames.append(df)
            else:
                logger.debug(f"Source fetcher {sg}: empty result")
        except Exception as exc:
            logger.warning(f"Source fetcher {sg} failed: {exc}")

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLS)

    merged = pd.concat(frames, ignore_index=True)
    merged = _ensure_output_cols(merged)
    before = len(merged)
    merged = merged.drop_duplicates(subset=["award_id"], keep="first")
    if before > len(merged):
        logger.debug(f"Deduplication removed {before - len(merged)} duplicate award_ids")

    logger.info(
        f"run_all_source_fetchers: {len(merged)} total rows from {len(frames)} sources, "
        f"source groups: {merged['source_group'].value_counts().to_dict()}"
    )
    return merged


# ── Public entry point ────────────────────────────────────────────────────────

def load_contracts(force_api: bool = False, use_native_fetchers: bool = True) -> pd.DataFrame:
    """Load contracts from all available sources.

    Priority:
      1. Local Contract_Sweeper CSV (all 8 source groups pre-merged)
      2. Native source fetchers (each portal queried independently)
      3. USASpending API live query (broadest fallback)

    Parameters
    ----------
    force_api : skip local files and query USASpending directly
    use_native_fetchers : try all 8 source fetchers before falling back to API

    Returns
    -------
    DataFrame with OUTPUT_COLS including source_group and source_group_weight.
    """
    if not force_api:
        df = load_from_contract_sweeper()
        if len(df) > 0:
            return df

        if use_native_fetchers:
            logger.info("No local contract CSV — trying native source fetchers...")
            df = run_all_source_fetchers()
            if len(df) > 0:
                return df

        logger.info("Native fetchers returned no data — falling back to USASpending API")

    return load_from_usaspending_api()


def source_group_summary(df: pd.DataFrame) -> dict:
    """Return row counts and total obligation by source group."""
    if df.empty or "source_group" not in df.columns:
        return {}
    summary = {}
    for sg, group in df.groupby("source_group"):
        summary[sg] = {
            "count":               len(group),
            "total_obligated_m":   round(group["obligated_amount"].sum() / 1e6, 2),
            "weight":              SOURCE_GROUP_WEIGHTS.get(sg, DEFAULT_SOURCE_WEIGHT),
        }
    return summary
