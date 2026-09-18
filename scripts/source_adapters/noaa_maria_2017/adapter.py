"""Certified discovery/fetch planning for NOAA Hurricane Maria imagery dataset 8507.

The adapter mirrors the shared Spiderweb-style acquisition substrate but keeps
Skywatcher-specific imagery lineage, rights, and calibration semantics.

Discovery metadata is small and may be fetched independently of raw imagery.
Raw TIFF acquisition is always delegated to CertifiedFetchEngine so staging,
SHA256, cache identity, hold behavior, and receipts remain uniform.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from scripts.source_adapters.sdk import AcquisitionRights, ImagerySourceEndpoint, PayloadRequest

DATASET_ID = "8507"
SOURCE_ID = "NOAA_MARIA_2017_8507"
DATASET_NAME = "2017 NOAA NGS DSS Natural Color 8 Bit Imagery: Hurricane Maria"
INDEX_URL = "https://chs.coast.noaa.gov/htdata/raster6/imagery/HurricaneMaria_2017_8507/index.html"
URL_LIST_URL = "https://chs.coast.noaa.gov/htdata/raster6/imagery/HurricaneMaria_2017_8507/urllist8507.txt"
STAC_ITEM_COLLECTION_URL = "https://chs.coast.noaa.gov/htdata/raster6/imagery/HurricaneMaria_2017_8507/stac/noaa_imagery_item_collection_m8507.json"
BULK_ROOT = "https://coastalimagery.blob.core.windows.net/digitalcoast/HurricaneMaria_2017_8507"
EXPECTED_TIFF_COUNT = 590
EXPECTED_STAC_ITEM_COUNT = 590
EXPECTED_URL_LIST_LINES = 1187
PUBLISHED_TOTAL_SIZE = "193G"
PUBLISHED_APPROX_GSD_CM = 25
PUBLISHED_DATE_START = "2017-09-22"
PUBLISHED_DATE_END = "2017-09-26"
PILOT_ITEM_ID = "20170924bC0660430w183000n"
PILOT_PUBLISHED_SIZE_MB = 3.99
ITEM_ID_RE = re.compile(r"^(?P<date>\d{8})(?P<batch>[A-Za-z])C(?P<rest>.+)$")


@dataclass(frozen=True)
class UrlListDenominator:
    tif_urls: tuple[str, ...]
    item_json_urls: tuple[str, ...]
    other_urls: tuple[str, ...]

    @property
    def tif_ids(self) -> tuple[str, ...]:
        return tuple(url.rsplit("/", 1)[-1].removesuffix(".tif") for url in self.tif_urls)

    @property
    def item_json_ids(self) -> tuple[str, ...]:
        return tuple(url.rsplit("/", 1)[-1].removesuffix(".json") for url in self.item_json_urls)

    def validate(self) -> None:
        if len(self.tif_urls) != EXPECTED_TIFF_COUNT:
            raise ValueError(f"TIFF denominator mismatch: {len(self.tif_urls)} != {EXPECTED_TIFF_COUNT}")
        if len(self.item_json_urls) != EXPECTED_STAC_ITEM_COUNT:
            raise ValueError(
                f"STAC-item denominator mismatch: {len(self.item_json_urls)} != {EXPECTED_STAC_ITEM_COUNT}"
            )
        if len(set(self.tif_urls)) != len(self.tif_urls):
            raise ValueError("duplicate TIFF URL in denominator")
        if len(set(self.item_json_urls)) != len(self.item_json_urls):
            raise ValueError("duplicate STAC item URL in denominator")
        if set(self.tif_ids) != set(self.item_json_ids):
            only_tif = sorted(set(self.tif_ids) - set(self.item_json_ids))[:10]
            only_json = sorted(set(self.item_json_ids) - set(self.tif_ids))[:10]
            raise ValueError(f"TIFF/STAC identity mismatch; tif_only={only_tif}, json_only={only_json}")


@dataclass(frozen=True)
class MariaItem:
    item_id: str
    asset_href: str
    asset_type: str
    bbox: tuple[float, float, float, float]
    proj_epsg: int | None
    proj_shape: tuple[int, int] | None
    stac_datetime: str
    filename_date_candidate: str
    time_state: str
    stac_license_raw: str
    source_lineage_id: str

    def to_manifest_row(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "asset_href": self.asset_href,
            "asset_type": self.asset_type,
            "bbox_west": self.bbox[0],
            "bbox_south": self.bbox[1],
            "bbox_east": self.bbox[2],
            "bbox_north": self.bbox[3],
            "proj_epsg": self.proj_epsg or "",
            "proj_height": self.proj_shape[0] if self.proj_shape else "",
            "proj_width": self.proj_shape[1] if self.proj_shape else "",
            "stac_datetime": self.stac_datetime,
            "filename_date_candidate": self.filename_date_candidate,
            "time_state": self.time_state,
            "stac_license_raw": self.stac_license_raw,
            "source_lineage_id": self.source_lineage_id,
            "lineage_semantics": "FILENAME_ACQUISITION_BATCH_CONSERVATIVE",
        }


def parse_url_list(text: str) -> UrlListDenominator:
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    tif_urls = tuple(line for line in lines if line.lower().endswith(".tif"))
    item_json_urls = tuple(
        line
        for line in lines
        if "/stac/" in line
        and line.lower().endswith(".json")
        and re.search(r"/stac/\d{8}[A-Za-z]C.+\.json$", line)
    )
    other_urls = tuple(line for line in lines if line not in set(tif_urls) and line not in set(item_json_urls))
    denominator = UrlListDenominator(tif_urls=tif_urls, item_json_urls=item_json_urls, other_urls=other_urls)
    denominator.validate()
    if len(lines) != EXPECTED_URL_LIST_LINES:
        raise ValueError(f"URL-list line denominator mismatch: {len(lines)} != {EXPECTED_URL_LIST_LINES}")
    return denominator


def _filename_date_and_lineage(item_id: str) -> tuple[str, str]:
    match = ITEM_ID_RE.match(item_id)
    if not match:
        return "UNKNOWN", f"{SOURCE_ID}::UNRESOLVED::{item_id}"
    raw = match.group("date")
    date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    batch = match.group("batch").lower()
    return date, f"{SOURCE_ID}::{raw}{batch}"


def _select_asset(feature: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    assets = feature.get("assets") or {}
    item_id = str(feature.get("id") or "")
    if item_id in assets:
        return item_id, dict(assets[item_id])
    image_assets = [(name, dict(asset)) for name, asset in assets.items() if str(asset.get("type", "")).startswith("image/")]
    if len(image_assets) != 1:
        raise ValueError(f"{item_id}: expected exactly one image asset, found {len(image_assets)}")
    return image_assets[0]


def parse_stac_collection(document: str | bytes | dict[str, Any]) -> tuple[MariaItem, ...]:
    if isinstance(document, (str, bytes)):
        payload = json.loads(document)
    else:
        payload = document
    if payload.get("type") != "FeatureCollection":
        raise ValueError("NOAA Maria STAC denominator must be a FeatureCollection")
    features = payload.get("features") or []
    if len(features) != EXPECTED_STAC_ITEM_COUNT:
        raise ValueError(f"STAC feature count mismatch: {len(features)} != {EXPECTED_STAC_ITEM_COUNT}")

    rows: list[MariaItem] = []
    seen: set[str] = set()
    for feature in features:
        item_id = str(feature.get("id") or "")
        if not item_id or item_id in seen:
            raise ValueError(f"missing/duplicate STAC item id: {item_id!r}")
        seen.add(item_id)
        _, asset = _select_asset(feature)
        href = str(asset.get("href") or "")
        if not href.lower().endswith(".tif"):
            raise ValueError(f"{item_id}: image asset is not a TIFF")
        bbox_raw = feature.get("bbox") or []
        if len(bbox_raw) != 4:
            raise ValueError(f"{item_id}: expected 4-element bbox")
        props = feature.get("properties") or {}
        stac_datetime = str(props.get("datetime") or "")
        filename_date, lineage = _filename_date_and_lineage(item_id)
        stac_date = stac_datetime[:10] if len(stac_datetime) >= 10 else "UNKNOWN"
        time_state = "MATCH" if stac_date == filename_date else "CONTRADICTION_TIME"
        shape_raw = asset.get("proj:shape")
        shape = tuple(int(v) for v in shape_raw) if isinstance(shape_raw, list) and len(shape_raw) == 2 else None
        epsg = asset.get("proj:epsg")
        rows.append(
            MariaItem(
                item_id=item_id,
                asset_href=href,
                asset_type=str(asset.get("type") or ""),
                bbox=tuple(float(v) for v in bbox_raw),
                proj_epsg=int(epsg) if epsg is not None else None,
                proj_shape=shape,
                stac_datetime=stac_datetime,
                filename_date_candidate=filename_date,
                time_state=time_state,
                stac_license_raw=str(props.get("license") or ""),
                source_lineage_id=lineage,
            )
        )
    return tuple(rows)


def discover_from_documents(url_list_text: str, stac_document: str | bytes | dict[str, Any]) -> tuple[UrlListDenominator, tuple[MariaItem, ...]]:
    denominator = parse_url_list(url_list_text)
    items = parse_stac_collection(stac_document)
    stac_ids = {item.item_id for item in items}
    if stac_ids != set(denominator.tif_ids):
        raise ValueError("URL-list TIFF ids do not close against STAC FeatureCollection ids")
    return denominator, items


def build_payload_request(item: MariaItem) -> PayloadRequest:
    endpoint = ImagerySourceEndpoint(
        source_id=SOURCE_ID,
        name=DATASET_NAME,
        url=item.asset_href,
        authority="NOAA National Geodetic Survey",
        source_lineage_id=item.source_lineage_id,
        imagery_provider="NOAA NGS",
        product_id=item.item_id,
        imagery_epoch=item.filename_date_candidate if item.time_state == "MATCH" else "UNKNOWN",
        rights=AcquisitionRights(fetch="ALLOWED", training="ALLOWED", redistribution="ALLOWED"),
        notes=(
            "Raw STAC license code is preserved separately. Dataset rights are bound through NOAA InPort (Access Constraints: None) plus the federal Data.gov record carrying CC0-1.0. "
            f"TIME_STATE={item.time_state}; filename_date_candidate={item.filename_date_candidate}; stac_datetime={item.stac_datetime}"
        ),
    )
    return PayloadRequest(
        request_id=f"noaa-maria-8507-{item.item_id}",
        endpoint=endpoint,
        expected_content="image",
        filename_hint=f"{item.item_id}.tif",
    )


def build_dry_run_plan(items: Iterable[MariaItem], selected_ids: set[str] | None = None) -> tuple[PayloadRequest, ...]:
    requests = []
    for item in items:
        if selected_ids is not None and item.item_id not in selected_ids:
            continue
        requests.append(build_payload_request(item))
    return tuple(requests)
