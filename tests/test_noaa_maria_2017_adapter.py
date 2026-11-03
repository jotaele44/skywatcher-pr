from __future__ import annotations

import json

import pytest

from scripts.source_adapters.noaa_maria_2017.adapter import (
    EXPECTED_STAC_ITEM_COUNT,
    EXPECTED_TIFF_COUNT,
    PILOT_ITEM_ID,
    build_payload_request,
    discover_from_documents,
    parse_stac_collection,
    parse_url_list,
)


def _item(item_id: str, *, stac_date: str | None = None) -> dict:
    date = item_id[:8]
    iso = stac_date or f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "properties": {"datetime": f"{iso}T00:00:00Z", "license": "NLPL"},
        "bbox": [-66.1, 18.4, -66.0, 18.5],
        "geometry": {"type": "Polygon", "coordinates": []},
        "assets": {
            item_id: {
                "href": f"https://example.noaa/{item_id}.tif",
                "type": "image/tiff",
                "proj:epsg": 4326,
                "proj:shape": [18681, 18681],
            }
        },
    }


def _ids() -> list[str]:
    return [f"20170924bC066{n:04d}w18{(n % 60):02d}00n" for n in range(EXPECTED_TIFF_COUNT)]


def _url_list(ids: list[str]) -> str:
    prefix = [
        "https://example.noaa/tileindex.zip",
        "https://example.noaa/metadata1.xml",
        "https://example.noaa/metadata2.xml",
        "stac/catalog.json",
        "stac/collection.json",
        "stac/items.json",
    ]
    tifs = [f"https://example.noaa/{item}.tif" for item in ids]
    stac_index = ["https://example.noaa/stac/index.html"]
    items = [f"https://example.noaa/stac/{item}.json" for item in ids]
    return "\n".join(prefix + tifs + stac_index + items)


def test_url_list_denominator_closes_one_to_one() -> None:
    ids = _ids()
    denominator = parse_url_list(_url_list(ids))
    assert len(denominator.tif_urls) == EXPECTED_TIFF_COUNT
    assert len(denominator.item_json_urls) == EXPECTED_STAC_ITEM_COUNT
    assert set(denominator.tif_ids) == set(denominator.item_json_ids)


def test_discovery_closes_url_list_against_stac() -> None:
    ids = _ids()
    stac = {"type": "FeatureCollection", "features": [_item(item) for item in ids]}
    denominator, items = discover_from_documents(_url_list(ids), stac)
    assert len(items) == EXPECTED_STAC_ITEM_COUNT
    assert len(denominator.tif_urls) == len(items)
    assert len({item.source_lineage_id for item in items}) == 1


def test_stac_datetime_conflict_is_preserved_not_overwritten() -> None:
    ids = _ids()
    features = [_item(item) for item in ids]
    features[0] = _item(ids[0], stac_date="2017-09-22")
    items = parse_stac_collection({"type": "FeatureCollection", "features": features})
    assert items[0].filename_date_candidate == "2017-09-24"
    assert items[0].stac_datetime.startswith("2017-09-22")
    assert items[0].time_state == "CONTRADICTION_TIME"
    request = build_payload_request(items[0])
    assert request.endpoint.imagery_epoch == "UNKNOWN"


def test_payload_request_preserves_conservative_batch_lineage() -> None:
    ids = _ids()
    items = parse_stac_collection({"type": "FeatureCollection", "features": [_item(item) for item in ids]})
    request = build_payload_request(items[0])
    assert request.endpoint.source_lineage_id.endswith("::20170924b")
    assert request.endpoint.rights.fetch == "ALLOWED"
    assert request.endpoint.rights.training == "ALLOWED"
    assert request.endpoint.rights.redistribution == "ALLOWED"
    assert request.expected_content == "image"


def test_real_pilot_identifier_is_stable_constant() -> None:
    assert PILOT_ITEM_ID == "20170924bC0660430w183000n"


def test_missing_stac_feature_fails_arithmetic_closure() -> None:
    ids = _ids()
    stac = {"type": "FeatureCollection", "features": [_item(item) for item in ids[:-1]]}
    with pytest.raises(ValueError, match="STAC feature count mismatch"):
        discover_from_documents(_url_list(ids), json.dumps(stac))
