"""
OCE_PR fetcher.

Source: ComprasPR — Puerto Rico's official electronic procurement portal, managed by the
Oficina de Gerencia y Presupuesto (OGP).  Records government purchase orders, awarded
contracts, and solicitations across all PR agencies.

Portal: https://compras.pr.gov
Data: https://data.pr.gov (Socrata — OGP procurement datasets)

Endpoints tried in order:
  1. data.pr.gov Socrata API — OGP/ComprasPR procurement datasets
  2. compras.pr.gov direct download links
  3. ogp.pr.gov alternate portal
  4. Manual fallback: data/raw/oce_pr.csv

No credentials required (public portal).
"""

import csv
import io
import logging

import pandas as pd

from .base import finalise, empty, load_cache, save_cache, safe_get, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "OCE_PR"

_SOCRATA_BASE = "https://data.pr.gov"
_SOCRATA_PAGE_SIZE = 1000

# Known OGP/ComprasPR dataset IDs on data.pr.gov
_KNOWN_DATASET_IDS = [
    "kwrj-vgaj",   # OGP purchase orders / órdenes de compra
    "wqkh-mvn6",   # ComprasPR awarded contracts
    "5x5m-8vqk",   # OGP contratos de servicios profesionales
    "tz3u-tj5j",   # Compras y contratos — general
]

# Direct download fallbacks
_DIRECT_URLS = [
    "https://data.pr.gov/api/views/kwrj-vgaj/rows.csv?accessType=DOWNLOAD",
    "https://data.pr.gov/api/views/wqkh-mvn6/rows.csv?accessType=DOWNLOAD",
    "https://compras.pr.gov/reports/contracts_awarded.csv",
    "https://ogp.pr.gov/sites/default/files/compraspuertorico/contratos_otorgados.csv",
]


def _fetch_socrata(dataset_id: str, session) -> list[dict]:
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


def _discover_oce_datasets(session) -> list[str]:
    resp = safe_get(
        f"{_SOCRATA_BASE}/api/catalog/v1",
        session=session,
        params={"q": "ComprasPR OGP contratos ordenes compra", "limit": "10"},
    )
    if resp is None:
        return []
    try:
        data = resp.json()
        return [
            r.get("resource", {}).get("id", "")
            for r in data.get("results", [])
            if r.get("resource", {}).get("id")
        ]
    except Exception:
        return []


def _map_row(r: dict) -> dict:
    amount = 0.0
    for f in ["monto", "award_amount", "precio", "total", "importe",
              "valor_contrato", "amount", "obligated_amount", "costo"]:
        try:
            v = float(str(r.get(f, 0) or 0).replace(",", "").replace("$", "").strip())
            if v:
                amount = v
                break
        except (ValueError, TypeError):
            pass

    vendor = ""
    for f in ["suplidor", "proveedor", "vendor_name", "nombre_suplidor",
              "nombre", "contractor", "contratista", "recipient"]:
        vendor = str(r.get(f, "") or "")
        if vendor:
            break

    desc = ""
    for f in ["descripcion", "description", "item", "producto", "objeto",
              "proyecto", "servicio", "articulo"]:
        desc = str(r.get(f, "") or "")
        if desc:
            break

    city = ""
    for f in ["municipio", "municipality", "ciudad", "town", "pueblo", "city"]:
        city = str(r.get(f, "") or "")
        if city:
            break

    aid = ""
    for f in ["orden_compra", "po_number", "contrato", "award_id",
              "numero", "id", "num_orden", "contract_number"]:
        aid = str(r.get(f, "") or "")
        if aid:
            break

    agency = ""
    for f in ["agencia", "agency", "entidad", "department", "departamento",
              "organismo"]:
        agency = str(r.get(f, "") or "")
        if agency:
            break

    date = ""
    for f in ["fecha", "date", "award_date", "fecha_orden", "fecha_inicio",
              "fecha_contrato"]:
        date = str(r.get(f, "") or "")
        if date:
            break

    return {
        "award_id":                   aid or f"OCE-{hash(vendor + desc) % 1000000}",
        "recipient_name":             vendor,
        "description":                desc,
        "obligated_amount":           amount,
        "award_date":                 date,
        "place_of_performance_city":  city,
        "place_of_performance_state": "PR",
        "awarding_agency_name":       agency or "OGP/ComprasPR",
        "naics_code":                 str(r.get("naics", r.get("naics_code", "")) or ""),
        "psc_code":                   "",
    }


def _fetch_direct_csv(url: str, session) -> list[dict]:
    resp = safe_get(url, session=session, timeout=60)
    if resp is None:
        return []
    try:
        reader = csv.DictReader(io.StringIO(resp.text))
        return [row for row in reader]
    except Exception as exc:
        logger.debug(f"CSV parse failed ({url}): {exc}")
        return []


def fetch(use_cache: bool = True) -> pd.DataFrame:
    """Fetch ComprasPR / OCE procurement data from data.pr.gov and OGP portals."""
    if use_cache:
        cached = load_cache(SOURCE_GROUP)
        if cached is not None:
            return cached

    session = get_session()
    all_rows: list[dict] = []

    # 1. Try known Socrata dataset IDs
    for dataset_id in _KNOWN_DATASET_IDS:
        rows = _fetch_socrata(dataset_id, session)
        if rows:
            logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from Socrata dataset {dataset_id}")
            all_rows.extend([_map_row(r) for r in rows])
            if len(all_rows) >= 500:
                break

    # 2. Discover additional OGP/ComprasPR datasets
    if not all_rows:
        discovered = _discover_oce_datasets(session)
        for dataset_id in discovered[:3]:
            rows = _fetch_socrata(dataset_id, session)
            if rows:
                logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from discovered dataset {dataset_id}")
                all_rows.extend([_map_row(r) for r in rows])
                if len(all_rows) >= 500:
                    break

    # 3. Direct CSV download fallbacks
    if not all_rows:
        for url in _DIRECT_URLS:
            csv_rows = _fetch_direct_csv(url, session)
            if csv_rows:
                logger.info(f"{SOURCE_GROUP}: {len(csv_rows)} rows from {url}")
                all_rows.extend([_map_row(r) for r in csv_rows])
                break

    if not all_rows:
        logger.warning(
            f"{SOURCE_GROUP}: no data retrieved. "
            "Manual export: https://compras.pr.gov or https://data.pr.gov (search 'OGP contratos') — "
            "download CSV and place in data/raw/oce_pr.csv"
        )
        from config import GEO_PR_INT_ROOT
        manual = GEO_PR_INT_ROOT / "data" / "raw" / "oce_pr.csv"
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
