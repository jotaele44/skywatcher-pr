"""
COR3_PR fetcher.

Source: Puerto Rico Central Office for Recovery, Reconstruction and Resiliency.
FEMA/COR3 manages billions in post-hurricane reconstruction contracts.

Data endpoints (tried in order):
  1. data.pr.gov Socrata API — searchable open data portal
  2. recovery.pr.gov downloadable project CSV
  3. HUD DRGR (Disaster Recovery Grant Reporting) public export

No credentials required.
"""

import csv
import io
import logging

import pandas as pd

from .base import finalise, empty, load_cache, save_cache, safe_get, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "COR3_PR"

# data.pr.gov Socrata catalog — COR3/CDBG-DR datasets
_SOCRATA_BASE = "https://data.pr.gov"
_SOCRATA_CATALOG = f"{_SOCRATA_BASE}/api/catalog/v1"
_SOCRATA_PAGE_SIZE = 1000

# Known dataset identifiers on data.pr.gov (COR3 project transparency data)
_KNOWN_DATASET_IDS = [
    "s8wr-bktx",   # CDBG-DR Action Plan projects
    "rnn9-c85i",   # COR3 infrastructure projects
    "6zb6-3z7y",   # PR Recovery projects tracker
    "cor3-awards", # may not exist — tried anyway
]

# Fallback direct download URLs from recovery.pr.gov
_DIRECT_URLS = [
    "https://recovery.pr.gov/en/download/projects",
    "https://recovery.pr.gov/files/COR3-Project-List.csv",
    "https://ogpe.pr.gov/documents/cor3-projects.csv",
]


def _fetch_socrata(dataset_id: str, session) -> list[dict]:
    """Fetch all rows from a data.pr.gov Socrata dataset."""
    url = f"{_SOCRATA_BASE}/resource/{dataset_id}.json"
    rows = []
    offset = 0
    while True:
        resp = safe_get(url, session=session, params={
            "$limit": str(_SOCRATA_PAGE_SIZE),
            "$offset": str(offset),
        })
        if resp is None:
            break
        try:
            page = resp.json()
        except Exception:
            break
        if not isinstance(page, list) or not page:
            break
        rows.extend(page)
        if len(page) < _SOCRATA_PAGE_SIZE:
            break
        offset += _SOCRATA_PAGE_SIZE
    return rows


def _discover_cor3_datasets(session) -> list[str]:
    """Search data.pr.gov catalog for COR3 / CDBG-DR datasets."""
    resp = safe_get(_SOCRATA_CATALOG, session=session, params={"q": "COR3 CDBG recovery", "limit": "10"})
    if resp is None:
        return []
    try:
        data = resp.json()
        results = data.get("results", [])
        return [r.get("resource", {}).get("id", "") for r in results if r.get("resource", {}).get("id")]
    except Exception:
        return []


def _socrata_row_to_dict(r: dict) -> dict:
    """Map Socrata fields to canonical contract schema."""
    # Try common COR3 field names
    amount = 0.0
    for f in ["total_amount", "award_amount", "obligated_amount", "amount", "federal_award_amount"]:
        try:
            amount = float(r.get(f, 0) or 0)
            if amount:
                break
        except (ValueError, TypeError):
            pass

    recipient = ""
    for f in ["vendor_name", "contractor_name", "recipient_name", "grantee_name", "developer"]:
        recipient = str(r.get(f, "") or "")
        if recipient:
            break

    desc = ""
    for f in ["project_description", "description", "activity_name", "project_name", "program"]:
        desc = str(r.get(f, "") or "")
        if desc:
            break

    city = ""
    for f in ["municipality", "city", "place_of_performance_city", "pop_city", "location"]:
        city = str(r.get(f, "") or "")
        if city:
            break

    aid = ""
    for f in ["award_id", "contract_id", "project_id", "grant_number", "subaward_id", "id"]:
        aid = str(r.get(f, "") or "")
        if aid:
            break

    return {
        "award_id":                   aid,
        "recipient_name":             recipient,
        "description":                desc,
        "obligated_amount":           amount,
        "award_date":                 str(r.get("start_date", r.get("award_date", r.get("date", ""))) or ""),
        "place_of_performance_city":  city,
        "place_of_performance_state": "PR",
        "awarding_agency_name":       str(r.get("awarding_agency", r.get("program_office", "COR3/FEMA")) or "COR3/FEMA"),
        "naics_code":                 str(r.get("naics_code", "") or ""),
        "psc_code":                   str(r.get("psc_code", "") or ""),
    }


def _fetch_direct_csv(url: str, session) -> list[dict]:
    """Download and parse a CSV from a direct URL."""
    resp = safe_get(url, session=session, timeout=60)
    if resp is None:
        return []
    try:
        content = resp.text
        reader = csv.DictReader(io.StringIO(content))
        return [row for row in reader]
    except Exception as exc:
        logger.debug(f"CSV parse failed ({url}): {exc}")
        return []


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch COR3/FEMA reconstruction contract data for Puerto Rico."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    session = get_session()
    all_rows: list[dict] = []

    # 1. Try known Socrata dataset IDs
    for dataset_id in _KNOWN_DATASET_IDS:
        if not dataset_id:
            continue
        rows = _fetch_socrata(dataset_id, session)
        if rows:
            logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from Socrata dataset {dataset_id}")
            all_rows.extend([_socrata_row_to_dict(r) for r in rows])
            break

    # 2. Discover additional datasets if still empty
    if not all_rows:
        discovered = _discover_cor3_datasets(session)
        for dataset_id in discovered[:3]:
            rows = _fetch_socrata(dataset_id, session)
            if rows:
                logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from discovered dataset {dataset_id}")
                all_rows.extend([_socrata_row_to_dict(r) for r in rows])
                if len(all_rows) >= 500:
                    break

    # 3. Fallback: direct CSV downloads from recovery.pr.gov
    if not all_rows:
        for url in _DIRECT_URLS:
            csv_rows = _fetch_direct_csv(url, session)
            if csv_rows:
                logger.info(f"{SOURCE_GROUP}: {len(csv_rows)} rows from {url}")
                all_rows.extend([_socrata_row_to_dict(r) for r in csv_rows])
                break

    if not all_rows:
        logger.warning(
            f"{SOURCE_GROUP}: no data retrieved. "
            "Manual export available at https://recovery.pr.gov/en/transparency/"
        )
        return empty()

    df = finalise(pd.DataFrame(all_rows), SOURCE_GROUP)
    # Filter to rows with non-zero amount or any description
    df = df[(df["obligated_amount"] > 0) | (df["description"] != "")].copy()
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} records fetched")
    return df
