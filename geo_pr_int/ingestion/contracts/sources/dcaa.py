"""
DCAA_CONTRACTOR_BASELINE fetcher.

Source: Defense Contract Audit Agency — DoD contractor baseline for Puerto Rico.
DCAA does not publish a standalone public API.  Data is assembled from:

  1. USASpending.gov — DoD awards placed in Puerto Rico (filtered by DoD agency)
  2. FPDS (Federal Procurement Data System) public search export
  3. Manual fallback: data/raw/dcaa.csv

The resulting records represent DoD/defense-related contract awards and serve as a
baseline for identifying defense contractors active in PR infrastructure.

No credentials required.
"""

import csv
import io
import logging
import time

import pandas as pd

from config import SETTINGS
from .base import finalise, empty, load_cache, save_cache, safe_get, safe_post, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "DCAA_CONTRACTOR_BASELINE"

_API_BASE = SETTINGS["usaspending"]["api_base"]
_PAGE_SIZE = 100
_MAX_PAGES = 5

# DoD agency filter keywords for USASpending
_DOD_KEYWORDS = [
    "construction", "engineering", "infrastructure",
    "utilities", "power", "water",
]

# FPDS public eZ Search export (no auth, CSV output)
_FPDS_URLS = [
    (
        "https://www.fpds.gov/ezsearch/search.do"
        "?indexName=awardfull&q=Puerto+Rico+construction&output=csv&SIGNED_DATE=%5B2018%2F01%2F01%2C%5D"
    ),
    (
        "https://www.fpds.gov/ezsearch/search.do"
        "?indexName=awardfull&q=Puerto+Rico+infrastructure&output=csv&SIGNED_DATE=%5B2018%2F01%2F01%2C%5D"
    ),
]

_USA_FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Start Date", "Description",
    "Place of Performance City Name", "Place of Performance State Code",
    "Awarding Agency Name", "NAICS Code", "PSC Code",
]


def _fetch_dod_usaspending(session) -> list[dict]:
    """Fetch DoD awards in PR from USASpending, capped to avoid rate-limit."""
    rows: list[dict] = []
    seen: set = set()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "GEO-PR-INT/1.0 (geospatial research)",
    }

    for kw in _DOD_KEYWORDS[:3]:
        for page in range(1, _MAX_PAGES + 1):
            url = f"{_API_BASE}/search/spending_by_award/"
            payload = {
                "filters": {
                    "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
                    "award_type_codes": ["A", "B", "C", "D"],
                    "keywords": [kw],
                    "agencies": [{"type": "awarding", "tier": "toptier",
                                  "name": "Department of Defense"}],
                },
                "fields": _USA_FIELDS,
                "page": page,
                "limit": _PAGE_SIZE,
                "sort": "Award Amount",
                "order": "desc",
            }
            resp = safe_post(url, payload, session=session, timeout=30)
            if resp is None:
                break
            try:
                results = resp.json().get("results", [])
            except Exception:
                break
            if not results:
                break
            for r in results:
                aid = r.get("Award ID", "")
                if aid not in seen:
                    seen.add(aid)
                    rows.append(r)
            if len(results) < _PAGE_SIZE:
                break
            time.sleep(0.3)

    return rows


def _usa_row_to_dict(r: dict) -> dict:
    return {
        "award_id":                   r.get("Award ID", ""),
        "recipient_name":             r.get("Recipient Name", ""),
        "description":                r.get("Description", ""),
        "obligated_amount":           float(r.get("Award Amount") or 0),
        "award_date":                 r.get("Start Date", ""),
        "place_of_performance_city":  r.get("Place of Performance City Name", ""),
        "place_of_performance_state": r.get("Place of Performance State Code", "PR"),
        "awarding_agency_name":       r.get("Awarding Agency Name", ""),
        "naics_code":                 str(r.get("NAICS Code", "") or ""),
        "psc_code":                   str(r.get("PSC Code", "") or ""),
    }


def _fetch_fpds_csv(session) -> list[dict]:
    """Try FPDS eZ Search public CSV export."""
    for url in _FPDS_URLS:
        resp = safe_get(url, session=session, timeout=60)
        if resp is None:
            continue
        if "text/csv" not in resp.headers.get("Content-Type", ""):
            # FPDS may return HTML login page — check for CSV content
            if not resp.text.startswith('"'):
                logger.debug(f"FPDS returned non-CSV response from {url}")
                continue
        try:
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = [_fpds_row(r) for r in reader]
            if rows:
                logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from FPDS export")
                return rows
        except Exception as exc:
            logger.debug(f"FPDS parse error ({url}): {exc}")
    return []


def _fpds_row(r: dict) -> dict:
    """Map FPDS CSV columns to canonical schema."""
    amount = 0.0
    for f in ["dollarsobligated", "obligatedamount", "baseandexercisedoptionsvalue",
              "baseandalloptionsvalue"]:
        try:
            v = float(str(r.get(f, 0) or 0).replace(",", "").replace("$", ""))
            if v:
                amount = v
                break
        except (ValueError, TypeError):
            pass

    vendor = ""
    for f in ["vendorname", "contractorname", "vendor_name"]:
        vendor = str(r.get(f, "") or "")
        if vendor:
            break

    city = ""
    for f in ["placeofperformancecity", "pop_city", "city"]:
        city = str(r.get(f, "") or "")
        if city:
            break

    return {
        "award_id":                   str(r.get("piid", r.get("contractid", "")) or ""),
        "recipient_name":             vendor,
        "description":                str(r.get("descriptionofcontractrequirement", r.get("description", "")) or ""),
        "obligated_amount":           amount,
        "award_date":                 str(r.get("signeddate", r.get("date", "")) or ""),
        "place_of_performance_city":  city,
        "place_of_performance_state": "PR",
        "awarding_agency_name":       str(r.get("contractingofficeagencyid", "DoD") or "DoD"),
        "naics_code":                 str(r.get("principalnaicscode", "") or ""),
        "psc_code":                   str(r.get("productorservicecode", "") or ""),
    }


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch DoD/DCAA contractor baseline for Puerto Rico."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    session = get_session()
    all_rows: list[dict] = []

    # 1. USASpending — DoD awards in PR
    usa_raw = _fetch_dod_usaspending(session)
    if usa_raw:
        logger.info(f"{SOURCE_GROUP}: {len(usa_raw)} rows from USASpending DoD filter")
        all_rows.extend([_usa_row_to_dict(r) for r in usa_raw])

    # 2. FPDS public CSV export
    if not all_rows:
        fpds_rows = _fetch_fpds_csv(session)
        if fpds_rows:
            all_rows.extend(fpds_rows)

    if not all_rows:
        logger.warning(
            f"{SOURCE_GROUP}: no data retrieved. "
            "Manual export: https://www.fpds.gov/fpdsng_cms/index.php/reports — "
            "download PR defense contracts CSV and place in data/raw/dcaa.csv"
        )
        from config import GEO_PR_INT_ROOT
        manual = GEO_PR_INT_ROOT / "data" / "raw" / "dcaa.csv"
        if manual.exists():
            try:
                df_manual = pd.read_csv(manual, low_memory=False)
                all_rows = df_manual.to_dict(orient="records")
                logger.info(f"{SOURCE_GROUP}: {len(all_rows)} rows from manual file")
            except Exception as exc:
                logger.warning(f"Manual file load failed: {exc}")

    if not all_rows:
        return empty()

    df = finalise(pd.DataFrame(all_rows), SOURCE_GROUP)
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} records fetched")
    return df
