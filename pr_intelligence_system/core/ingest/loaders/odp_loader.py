import logging
import os
import time
import zipfile
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

ODP_ENDPOINT  = "https://odp.dataspace.copernicus.eu/odata/v1"
CAT_ENDPOINT  = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
AUTH_ENDPOINT = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
    "/protocol/openid-connect/token"
)
CARD_BS_WORKFLOW = "card_bs"
MAX_PRODUCTS  = 3
POLL_INTERVAL = 30   # seconds
POLL_TIMEOUT  = 3600  # 1 hour


def get_token(username: str, password: str) -> str:
    """Acquire a Keycloak Bearer token using username + password credentials."""
    resp = requests.post(
        AUTH_ENDPOINT,
        data={
            "client_id": "cdse-public",
            "username": username,
            "password": password,
            "grant_type": "password",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise ConnectionError(
            f"ODP authentication failed ({resp.status_code}): {resp.text[:200]}\n"
            f"Check CDSE_USER / CDSE_PASSWORD environment variables."
        )
    token = resp.json().get("access_token")
    if not token:
        raise ConnectionError("ODP auth response missing access_token.")
    logger.info("ODP token acquired.")
    return token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _bbox_to_wkt(bbox: dict) -> str:
    """Convert {west, south, east, north} to WKT POLYGON string."""
    w, s, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    return (
        f"POLYGON (({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"
    )


def find_s1_grd_products(
    bbox: dict,
    temporal_extent: list,
    token: str,
) -> list:
    """
    Search the CDSE catalogue for online S1 IW GRD products intersecting the AOI.

    Returns list of product Name strings (.SAFE identifiers), most recent first,
    limited to MAX_PRODUCTS. Returns [] if none found.
    """
    start, end = temporal_extent[0], temporal_extent[1]
    wkt = _bbox_to_wkt(bbox)

    odata_filter = (
        f"(ContentDate/Start ge {start}T00:00:00.000Z "
        f"and ContentDate/Start le {end}T23:59:59.999Z) "
        f"and (Online eq true) "
        f"and (OData.CSC.Intersects(Footprint=geography'SRID=4326;{wkt}')) "
        f"and (Collection/Name eq 'SENTINEL-1') "
        f"and (Attributes/OData.CSC.StringAttribute/any("
        f"i0:i0/Name eq 'productType' and i0/Value eq 'IW_GRDH_1S'))"
    )

    resp = requests.get(
        CAT_ENDPOINT,
        params={
            "$filter": odata_filter,
            "$orderby": "ContentDate/Start desc",
            "$top": MAX_PRODUCTS,
        },
        headers=_auth_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("value", [])
    names = [item["Name"] for item in items if "Name" in item]
    logger.info("Catalogue: found %d S1 GRD product(s) for AOI.", len(names))
    return names


def submit_card_bs_order(product_name: str, token: str, order_label: str) -> str:
    """
    Submit a CARD-BS production order for a single S1 GRD product.
    Returns the order Id string.
    """
    body = {
        "WorkflowName": CARD_BS_WORKFLOW,
        "InputProductReference": {"Reference": product_name},
        "WorkflowOptions": [{"Name": "output_storage", "Value": "TEMPORARY"}],
        "Priority": 1,
        "Name": order_label,
    }
    resp = requests.post(
        f"{ODP_ENDPOINT}/ProductionOrder/OData.CSC.Order",
        json=body,
        headers={**_auth_headers(token), "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    order_id = resp.json()["value"]["Id"]
    logger.info("Submitted CARD-BS order %s for %s.", order_id, product_name)
    return str(order_id)


TOKEN_REFRESH_INTERVAL = 480  # refresh token every 8 min (expires ~10 min)


def poll_order(
    order_id: str,
    token: str,
    username: str = None,
    password: str = None,
) -> str:
    """
    Poll until order is 'completed' or 'failed'. Returns 'completed'.
    Raises RuntimeError on failure or timeout.

    If username and password are provided, the token is refreshed every
    TOKEN_REFRESH_INTERVAL seconds to handle long-running CARD-BS jobs
    that outlast the ~10-minute Keycloak token expiry.
    """
    deadline = time.time() + POLL_TIMEOUT
    last_refresh = time.time()

    while time.time() < deadline:
        # Refresh token before it expires if credentials are available
        if username and password and (time.time() - last_refresh) > TOKEN_REFRESH_INTERVAL:
            try:
                token = get_token(username, password)
                last_refresh = time.time()
                logger.debug("ODP token refreshed for order %s.", order_id)
            except Exception as exc:
                logger.warning("Token refresh failed (%s); continuing with existing token.", exc)

        resp = requests.get(
            f"{ODP_ENDPOINT}/ProductionOrders({order_id})",
            headers=_auth_headers(token),
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("Status", "").lower()
        msg = resp.json().get("StatusMessage", "")
        logger.info("Order %s: %s — %s", order_id, status, msg)

        if status == "completed":
            return "completed"
        if status in ("failed", "cancelled"):
            raise RuntimeError(
                f"ODP order {order_id} {status}: {msg}"
            )
        time.sleep(POLL_INTERVAL)

    raise RuntimeError(
        f"ODP order {order_id} did not complete within {POLL_TIMEOUT}s."
    )


def download_order_result(order_id: str, token: str, output_dir: str) -> list:
    """
    Download order result ZIP, extract GeoTIFFs, rename with 'sar_' prefix.
    Returns list of extracted .tif paths.
    """
    zip_path = os.path.join(output_dir, f"order_{order_id}.zip")
    resp = requests.get(
        f"{ODP_ENDPOINT}/ProductionOrder({order_id})/Product/$value",
        headers=_auth_headers(token),
        stream=True,
        timeout=300,
    )
    resp.raise_for_status()

    with open(zip_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    logger.info("Downloaded order %s result to %s.", order_id, zip_path)

    tif_paths = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.lower().endswith(".tif"):
                basename = os.path.basename(name)
                if not basename.startswith("sar_"):
                    basename = "sar_" + basename
                dest = os.path.join(output_dir, basename)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                tif_paths.append(dest)

    os.remove(zip_path)
    logger.info("Extracted %d SAR GeoTIFF(s) from order %s.", len(tif_paths), order_id)
    return tif_paths


def fetch_sar(
    bbox: dict,
    temporal_extent: list,
    output_dir: str,
    aoi_id: str,
    username: str,
    password: str,
) -> list:
    """
    Full SAR fetch pipeline: authenticate → find GRD products → submit CARD-BS
    orders → poll → download → return list of sar_*.tif paths.

    Each product order is attempted independently; individual failures are
    logged and skipped. Returns [] if no products found or all orders fail.
    """
    os.makedirs(output_dir, exist_ok=True)

    token = get_token(username, password)
    products = find_s1_grd_products(bbox, temporal_extent, token)

    if not products:
        logger.warning(
            "No S1 GRD products found for AOI %s in %s – %s.",
            aoi_id, temporal_extent[0], temporal_extent[1],
        )
        return []

    all_tif_paths = []
    for i, product_name in enumerate(products):
        order_label = f"pr_int_{aoi_id}_sar_{i}"
        try:
            order_id = submit_card_bs_order(product_name, token, order_label)
            poll_order(order_id, token, username=username, password=password)
            tif_paths = download_order_result(order_id, token, output_dir)
            all_tif_paths.extend(tif_paths)
        except Exception as exc:
            logger.warning(
                "SAR order for %s failed (%s); skipping.", product_name, exc
            )

    logger.info("SAR fetch complete: %d GeoTIFF(s) for AOI %s.", len(all_tif_paths), aoi_id)
    return all_tif_paths
