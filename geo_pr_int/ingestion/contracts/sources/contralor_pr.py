"""
CONTRALOR_PR fetcher.

Source: Oficina del Contralor de Puerto Rico (OCPR) — ocpr.gov.pr
The PR Controller maintains a mandatory contract registry: all government
agencies must register contracts >$50,000 within 30 days of execution.

Portal: https://www.ocpr.gov.pr/
Contract search: https://www.ocpr.gov.pr/informes/contratos/

Approach:
  1. POST the contract search form to retrieve HTML tables
  2. Parse table rows into canonical contract records
  3. Paginate through all results

No credentials required (public portal).
"""

import logging
import re
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from .base import finalise, empty, load_cache, save_cache, safe_get, safe_post, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "CONTRALOR_PR"

_BASE_URL = "https://www.ocpr.gov.pr"
_SEARCH_URL = f"{_BASE_URL}/contratos/"
_SEARCH_URL_ALT = f"{_BASE_URL}/informes/contratos/"

# Alternative: the SICI (Sistema Integrado de Información de Contratos e Informes)
_SICI_URL = "https://sici.ocpr.gov.pr/"
_SICI_API = "https://sici.ocpr.gov.pr/api/contratos"


def _parse_contracts_table(html: str) -> list[dict]:
    """Parse HTML table of contracts from OCPR portal."""
    rows = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", {"class": re.compile(r"contract|tabla|table", re.I)})
        if table is None:
            table = soup.find("table")
        if table is None:
            return []

        headers = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all(["th", "td"])]
        else:
            first_row = table.find("tr")
            if first_row:
                headers = [td.get_text(strip=True).lower() for td in first_row.find_all(["th", "td"])]

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or len(cells) < 3:
                continue
            row = dict(zip(headers, cells)) if headers else {str(i): v for i, v in enumerate(cells)}
            rows.append(row)
    except Exception as exc:
        logger.debug(f"Table parse error: {exc}")
    return rows


def _map_row(r: dict) -> dict:
    """Map OCPR row dict to canonical schema."""
    amount = 0.0
    for f in ["monto", "amount", "importe", "valor", "total", "contract amount"]:
        val = r.get(f, "")
        if val:
            try:
                amount = float(str(val).replace(",", "").replace("$", "").strip())
                break
            except ValueError:
                pass

    vendor = ""
    for f in ["contratista", "vendor", "contractor", "recipient", "proveedor", "nombre"]:
        vendor = r.get(f, "")
        if vendor:
            break

    desc = ""
    for f in ["descripcion", "description", "objeto", "purpose", "servicio", "proyecto"]:
        desc = r.get(f, "")
        if desc:
            break

    city = ""
    for f in ["municipio", "ciudad", "city", "municipality", "pueblo"]:
        city = r.get(f, "")
        if city:
            break

    aid = ""
    for f in ["num_contrato", "contract_no", "numero", "id", "referencia"]:
        aid = r.get(f, "")
        if aid:
            break

    date = ""
    for f in ["fecha", "date", "fecha_inicio", "award_date"]:
        date = r.get(f, "")
        if date:
            break

    agency = ""
    for f in ["agencia", "agency", "entidad", "entity"]:
        agency = r.get(f, "")
        if agency:
            break

    return {
        "award_id":                   aid or f"OCPR-{hash(vendor + desc) % 1000000}",
        "recipient_name":             vendor,
        "description":                desc,
        "obligated_amount":           amount,
        "award_date":                 date,
        "place_of_performance_city":  city,
        "place_of_performance_state": "PR",
        "awarding_agency_name":       agency or "OCPR",
        "naics_code":                 "",
        "psc_code":                   "",
    }


def _try_sici_api(session) -> list[dict]:
    """Try the SICI modern API if available."""
    for url in [_SICI_API, f"{_SICI_URL}api/contratos", f"{_SICI_URL}contratos.json"]:
        resp = safe_get(url, session=session, timeout=30)
        if resp is None:
            continue
        try:
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"]
        except Exception:
            pass
    return []


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch PR government contracts from OCPR (Contralor de Puerto Rico)."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    session = get_session()
    all_rows: list[dict] = []

    # 1. Try the SICI API (modern JSON endpoint)
    sici_rows = _try_sici_api(session)
    if sici_rows:
        logger.info(f"{SOURCE_GROUP}: {len(sici_rows)} rows from SICI API")
        all_rows = [_map_row(r) for r in sici_rows]

    # 2. Scrape the OCPR contract search portal
    if not all_rows:
        for search_url in [_SEARCH_URL, _SEARCH_URL_ALT]:
            resp = safe_get(search_url, session=session, timeout=30)
            if resp is None:
                continue
            html_rows = _parse_contracts_table(resp.text)
            if html_rows:
                logger.info(f"{SOURCE_GROUP}: {len(html_rows)} rows from {search_url}")
                all_rows = [_map_row(r) for r in html_rows]
                break

            # Try POST with a year-range search form
            current_year = datetime.now().year
            form_payload = {
                "ano_desde": str(current_year - 5),
                "ano_hasta": str(current_year),
                "agencia":   "",
                "vendor":    "",
                "submit":    "Buscar",
            }
            resp2 = safe_post(search_url, form_payload, session=session, timeout=30)
            if resp2:
                html_rows = _parse_contracts_table(resp2.text)
                if html_rows:
                    logger.info(f"{SOURCE_GROUP}: {len(html_rows)} rows (POST search)")
                    all_rows = [_map_row(r) for r in html_rows]
                    break

    if not all_rows:
        logger.warning(
            f"{SOURCE_GROUP}: could not retrieve data. "
            "Manual export: https://www.ocpr.gov.pr/contratos/ — "
            "download the Excel/CSV and place in data/raw/contralor_pr.csv"
        )
        # Check for manually downloaded file
        from config import GEO_PR_INT_ROOT
        manual = GEO_PR_INT_ROOT / "data" / "raw" / "contralor_pr.csv"
        if manual.exists():
            try:
                df = pd.read_csv(manual, low_memory=False)
                logger.info(f"{SOURCE_GROUP}: loaded {len(df)} rows from manual export")
                all_rows = df.to_dict(orient="records")
            except Exception as exc:
                logger.warning(f"Manual file load failed: {exc}")

    if not all_rows:
        return empty()

    df = finalise(pd.DataFrame(all_rows), SOURCE_GROUP)
    save_cache(df, SOURCE_GROUP)
    logger.info(f"{SOURCE_GROUP}: {len(df)} contract records fetched")
    return df
