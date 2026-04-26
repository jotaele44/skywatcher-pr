"""
FSRS_SUBAWARDS fetcher.

Source: api.usaspending.gov/api/v2/subawards/ — federal subaward data
(FSRS = Federal Subaward Reporting System, now hosted on USASpending).
Subawards capture the actual construction / subcontracting companies doing
infrastructure work in Puerto Rico.
No credentials required.
"""

import logging
import time

import pandas as pd

from config import SETTINGS
from .base import finalise, empty, load_cache, save_cache, safe_post

logger = logging.getLogger(__name__)

SOURCE_GROUP = "FSRS_SUBAWARDS"
_API_BASE = SETTINGS["usaspending"]["api_base"]
_PAGE_SIZE = 100
_MAX_PAGES = 20

_FIELDS = [
    "subaward_number", "description", "amount",
    "recipient_name", "recipient_location_city_name",
    "recipient_location_state_code", "awarding_agency_name",
    "sub_action_date", "prime_award_id",
]


def _page(page: int, award_type: str = "procurement") -> list[dict]:
    url = f"{_API_BASE}/subawards/"
    payload = {
        "page": page,
        "limit": _PAGE_SIZE,
        "sort": "amount",
        "order": "desc",
        "filters": {
            "award_type": award_type,
            "place_of_performance_scope": "domestic",
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        },
        "fields": _FIELDS,
    }
    resp = safe_post(url, payload, timeout=45)
    if resp is None:
        return []
    try:
        data = resp.json()
        return data.get("results", [])
    except Exception:
        return []


def _row(r: dict) -> dict:
    return {
        "award_id":                   str(r.get("subaward_number", "") or r.get("prime_award_id", "")),
        "recipient_name":             r.get("recipient_name", ""),
        "description":                r.get("description", ""),
        "obligated_amount":           float(r.get("amount") or 0),
        "award_date":                 r.get("sub_action_date", ""),
        "place_of_performance_city":  r.get("recipient_location_city_name", ""),
        "place_of_performance_state": r.get("recipient_location_state_code", "PR"),
        "awarding_agency_name":       r.get("awarding_agency_name", ""),
        "naics_code":                 "",
        "psc_code":                   "",
    }


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch PR federal subawards from USASpending (FSRS data)."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    rows: list[dict] = []
    seen: set = set()

    for award_type in ["procurement", "grant"]:
        for page in range(1, _MAX_PAGES + 1):
            page_rows = _page(page, award_type)
            if not page_rows:
                break
            for r in page_rows:
                key = str(r.get("subaward_number", "")) + str(r.get("prime_award_id", ""))
                if key not in seen:
                    seen.add(key)
                    rows.append(_row(r))
            if len(page_rows) < _PAGE_SIZE:
                break
            time.sleep(0.2)

    if not rows:
        logger.warning(f"{SOURCE_GROUP}: no subawards returned")
        return empty()

    df = finalise(pd.DataFrame(rows), SOURCE_GROUP)
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} subawards fetched")
    return df
