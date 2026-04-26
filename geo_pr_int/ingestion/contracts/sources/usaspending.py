"""
USASPENDING_FEDERAL fetcher.

Source: api.usaspending.gov — federal contract awards placed in Puerto Rico.
No credentials required. May return 403 if rate-limited from server IPs.
"""

import logging
import time

import pandas as pd

from config import SETTINGS
from .base import finalise, empty, load_cache, save_cache, safe_post

logger = logging.getLogger(__name__)

SOURCE_GROUP = "USASPENDING_FEDERAL"
_API = SETTINGS["usaspending"]["api_base"]
_KEYWORDS = SETTINGS["usaspending"]["keywords"]
_MAX_PAGES = int(SETTINGS["usaspending"].get("max_pages", 10))
_PAGE_SIZE = int(SETTINGS["usaspending"].get("page_size", 100))

_FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Start Date", "Description",
    "Place of Performance City Name", "Place of Performance State Code",
    "Awarding Agency Name", "NAICS Code", "PSC Code",
]


def _page(keyword: str, page: int) -> list[dict]:
    url = f"{_API}/search/spending_by_award/"
    payload = {
        "filters": {
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
            "award_type_codes": ["A", "B", "C", "D"],
            "keywords": [keyword],
        },
        "fields": _FIELDS,
        "page": page,
        "limit": _PAGE_SIZE,
        "sort": "Award Amount",
        "order": "desc",
    }
    resp = safe_post(url, payload)
    if resp is None:
        return []
    try:
        return resp.json().get("results", [])
    except Exception:
        return []


def _row(r: dict) -> dict:
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


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch PR federal contract awards from USASpending.gov."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    rows: list[dict] = []
    seen: set = set()

    for kw in _KEYWORDS[:5]:
        for page in range(1, _MAX_PAGES + 1):
            page_rows = _page(kw, page)
            if not page_rows:
                break
            for r in page_rows:
                aid = r.get("Award ID", "")
                if aid not in seen:
                    seen.add(aid)
                    rows.append(_row(r))
            if len(page_rows) < _PAGE_SIZE:
                break
            time.sleep(0.2)

    if not rows:
        logger.warning(f"{SOURCE_GROUP}: no rows returned (API may be rate-limiting this IP)")
        return empty()

    df = finalise(pd.DataFrame(rows), SOURCE_GROUP)
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} awards fetched")
    return df
