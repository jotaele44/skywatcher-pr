"""
OGPE_PR fetcher.

Source: Oficina de Gerencia y Presupuesto (OGPE) — Puerto Rico Office of Management
and Budget.  OGPE publishes budget execution data, inter-agency transfers, and
contractor payment records via the PR Open Data portal (data.pr.gov) and the
OGPE transparency portal.

Endpoints tried in order:
  1. data.pr.gov Socrata API — OGPE/budget datasets
  2. ogpe.pr.gov direct CSV exports (budget execution, contratos)
  3. Fiscal transparency portal (transparencia.pr.gov)

No credentials required (public data).
"""

import logging

import pandas as pd

from .base import finalise, empty, load_cache, save_cache, safe_get, get_session

logger = logging.getLogger(__name__)

SOURCE_GROUP = "OGPE_PR"

_SOCRATA_BASE = "https://data.pr.gov"
_SOCRATA_PAGE_SIZE = 1000

# Known OGPE dataset IDs on data.pr.gov
_KNOWN_DATASET_IDS = [
    "gn6k-7hqp",   # OGPE presupuesto por agencia
    "h6bz-5p8s",   # Contratos de servicios
    "q7em-g94n",   # Ejecucion presupuestaria
    "d4z3-kzzd",   # OGPE transparency — general
]

# Direct download fallbacks
_DIRECT_URLS = [
    "https://data.pr.gov/api/views/gn6k-7hqp/rows.csv?accessType=DOWNLOAD",
    "https://transparencia.pr.gov/wp-content/uploads/contratos.csv",
    "https://www.ogpe.pr.gov/sites/default/files/documentos/contratos_vigentes.csv",
    "https://data.pr.gov/api/views/h6bz-5p8s/rows.csv?accessType=DOWNLOAD",
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


def _discover_ogpe_datasets(session) -> list[str]:
    resp = safe_get(
        f"{_SOCRATA_BASE}/api/catalog/v1",
        session=session,
        params={"q": "OGPE contratos presupuesto", "limit": "10"},
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
    for f in ["amount", "monto", "total", "valor", "importe", "award_amount",
              "obligated_amount", "budget_amount", "presupuesto"]:
        try:
            v = float(str(r.get(f, 0) or 0).replace(",", "").replace("$", "").strip())
            if v:
                amount = v
                break
        except (ValueError, TypeError):
            pass

    vendor = ""
    for f in ["vendor", "contratista", "contractor", "recipient", "beneficiario",
              "suplidor", "proveedor", "nombre_contratista", "nombre"]:
        vendor = str(r.get(f, "") or "")
        if vendor:
            break

    desc = ""
    for f in ["description", "descripcion", "objeto", "project_name", "proyecto",
              "activity", "servicio", "partida"]:
        desc = str(r.get(f, "") or "")
        if desc:
            break

    city = ""
    for f in ["municipality", "municipio", "city", "ciudad", "pueblo", "location"]:
        city = str(r.get(f, "") or "")
        if city:
            break

    aid = ""
    for f in ["contract_id", "award_id", "num_contrato", "numero", "id",
              "contrato_numero", "referencia"]:
        aid = str(r.get(f, "") or "")
        if aid:
            break

    agency = ""
    for f in ["agency", "agencia", "entity", "entidad", "department", "departamento"]:
        agency = str(r.get(f, "") or "")
        if agency:
            break

    date = ""
    for f in ["date", "fecha", "start_date", "award_date", "fecha_inicio"]:
        date = str(r.get(f, "") or "")
        if date:
            break

    return {
        "award_id":                   aid or f"OGPE-{hash(vendor + desc) % 1000000}",
        "recipient_name":             vendor,
        "description":                desc,
        "obligated_amount":           amount,
        "award_date":                 date,
        "place_of_performance_city":  city,
        "place_of_performance_state": "PR",
        "awarding_agency_name":       agency or "OGPE",
        "naics_code":                 "",
        "psc_code":                   "",
    }


def _fetch_direct_csv(url: str, session) -> list[dict]:
    import csv, io
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
    """Fetch OGPE budget/contract data from data.pr.gov and OGPE portals."""
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

    # 2. Discover additional OGPE datasets
    if not all_rows:
        discovered = _discover_ogpe_datasets(session)
        for dataset_id in discovered[:3]:
            rows = _fetch_socrata(dataset_id, session)
            if rows:
                logger.info(f"{SOURCE_GROUP}: {len(rows)} rows from discovered dataset {dataset_id}")
                all_rows.extend([_map_row(r) for r in rows])
                if len(all_rows) >= 500:
                    break

    # 3. Direct CSV fallbacks
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
            "Manual export: https://data.pr.gov (search 'OGPE contratos') — "
            "download CSV and place in data/raw/ogpe_pr.csv"
        )
        from config import GEO_PR_INT_ROOT
        manual = GEO_PR_INT_ROOT / "data" / "raw" / "ogpe_pr.csv"
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
