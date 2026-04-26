"""
SAM_ENTITY_REGISTRY fetcher.

Source: api.sam.gov — System for Award Management entity registry.
Captures active registered contractors/vendors operating in Puerto Rico.

Requires a free API key: https://open.gsa.gov/api/sam-entity-extracts-api/
Set env var SAM_API_KEY=<your_key> before running.
Without a key, falls back to the public beta endpoint (limited results).
"""

import logging
import os
import time

import pandas as pd

from .base import finalise, empty, load_cache, save_cache, safe_get, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "SAM_ENTITY_REGISTRY"
_API_BASE = "https://api.sam.gov/entity-information/v3/entities"
_PAGE_SIZE = 100


def _build_params(offset: int, api_key: str | None) -> dict:
    params = {
        "physicalAddress.stateOrProvinceCode": "PR",
        "registrationStatus": "A",       # Active
        "entityType": "2~3",             # Business + Individual
        "purposeOfRegistrationCode": "Z2",  # all awards
        "size": str(_PAGE_SIZE),
        "start": str(offset),
    }
    if api_key:
        params["api_key"] = api_key
    return params


def _row(entity: dict) -> dict:
    core = entity.get("entityRegistration", {})
    address = entity.get("coreData", {}).get("physicalAddress", {})
    name = core.get("legalBusinessName", "")
    uei = core.get("ueiSAM", core.get("uei", ""))
    city = address.get("city", "")
    state = address.get("stateOrProvinceCode", "PR")
    naics_list = entity.get("assertions", {}).get("naicsCode", [])
    naics = naics_list[0].get("naicsCode", "") if naics_list else ""

    return {
        "award_id":                   f"SAM-{uei}",
        "recipient_name":             name,
        "description":                f"SAM registered entity: {name}",
        "obligated_amount":           0.0,  # entity registry — no award amounts
        "award_date":                 core.get("registrationDate", ""),
        "place_of_performance_city":  city,
        "place_of_performance_state": state,
        "awarding_agency_name":       "SAM.gov",
        "naics_code":                 str(naics),
        "psc_code":                   "",
    }


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch active PR-registered entities from SAM.gov."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    api_key = os.environ.get("SAM_API_KEY", "")
    if not api_key:
        logger.warning(
            f"{SOURCE_GROUP}: SAM_API_KEY not set. "
            "Get a free key at https://open.gsa.gov/api/sam-entity-extracts-api/ "
            "and set env var SAM_API_KEY=<key>. Attempting public endpoint..."
        )

    session = get_session()
    session.headers["Accept"] = "application/json"

    rows: list[dict] = []
    offset = 0
    max_pages = 20

    for _ in range(max_pages):
        params = _build_params(offset, api_key or None)
        resp = safe_get(_API_BASE, session=session, params=params, timeout=30)
        if resp is None:
            break

        try:
            data = resp.json()
        except Exception:
            break

        entities = data.get("entityData", [])
        if not entities:
            break

        for e in entities:
            rows.append(_row(e))

        total = int(data.get("totalRecords", 0))
        offset += _PAGE_SIZE
        if offset >= total:
            break
        time.sleep(0.3)

    if not rows:
        logger.warning(f"{SOURCE_GROUP}: no entities returned — API key may be required")
        return empty()

    df = finalise(pd.DataFrame(rows), SOURCE_GROUP)
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} entities fetched")
    return df
