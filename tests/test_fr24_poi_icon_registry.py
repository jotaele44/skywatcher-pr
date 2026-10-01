from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

from skywatcher.registry.fr24_poi_icons import (
    allowed_icon_class_ids,
    load_registry,
    resolve_icon_class,
    validate_registry,
    verify_source_archive,
)

REPO = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO / "configs" / "fr24_poi_icon_registry.json"


def test_fr24_poi_icon_registry_is_closed_and_valid() -> None:
    data = load_registry(REGISTRY_PATH)
    result = validate_registry(data)
    assert result["status"] == "pass", result["failures"]
    assert result["counts"] == {
        "canonical_feature_types": 26,
        "source_icon_types": 33,
        "reserved_non_poi_icon_classes": 7,
        "source_manifestations": 34,
        "archive_members": 68,
        "semantic_archive_members": 34,
    }


def test_route_markers_are_transport_features_not_pois() -> None:
    data = load_registry(REGISTRY_PATH)
    by_id = {
        row["canonical_type_id"]: row for row in data["canonical_feature_types"]
    }
    for cid in ("ROAD_ROUTE_MARKER", "AVENUE_ROUTE_MARKER"):
        assert by_id[cid]["feature_kind"] == "TRANSPORT_FEATURE"
        assert by_id[cid]["poi_eligible"] is False


def test_composite_source_crops_preserve_multiple_visible_glyphs() -> None:
    data = load_registry(REGISTRY_PATH)
    composites = [
        row
        for row in data["source_manifestations"]
        if row.get("composite_source_crop")
    ]
    assert {row["raw_member_path"] for row in composites} == {
        "Icon Library/poi_types/parking & ban╠âos.heic",
        "Icon Library/poi_types/pizza & barberi╠üa.heic",
    }
    assert all(len(row["source_type_ids"]) == 2 for row in composites)


def test_manifestation_ids_are_content_bound() -> None:
    data = load_registry(REGISTRY_PATH)
    for row in data["source_manifestations"]:
        assert row["manifestation_id"] == "FR24SRC_" + row["sha256"][:16].upper()


def test_operator_logo_sources_cannot_become_poi_types() -> None:
    data = load_registry(REGISTRY_PATH)
    operator_rows = [
        row
        for row in data["source_manifestations"]
        if row["entity_kind"] == "OPERATOR_LOGO_SOURCE"
    ]
    assert len(operator_rows) == 3
    for row in operator_rows:
        assert row["source_type_ids"] == []
        assert row["identity_status"] == "CANDIDATE_NOT_IDENTITY"


def test_national_guard_filename_does_not_promote_national_guard_identity() -> None:
    data = load_registry(REGISTRY_PATH)
    row = next(
        row
        for row in data["source_icon_types"]
        if row["source_type_id"] == "FR24_MILITARY_FACILITY"
    )
    assert row["canonical_type_id"] == "MILITARY_FACILITY"
    assert "does not establish National Guard identity" in row["notes"]


def test_legacy_operator_labels_resolve_only_through_declared_aliases() -> None:
    data = load_registry(REGISTRY_PATH)
    airport = resolve_icon_class("airport", data)
    assert airport["resolution_status"] == "resolved"
    assert airport["icon_class_id"] == "FR24_AIRPORT"

    chrome = resolve_icon_class("ui_chrome", data)
    assert chrome["resolution_status"] == "resolved"
    assert chrome["icon_class_id"] == "FR24_UI_CHROME"

    unknown = resolve_icon_class("definitely-not-a-declared-class", data)
    assert unknown["resolution_status"] == "unresolved"
    assert unknown["candidates"] == []


def test_allowed_icon_classes_include_seed_and_non_poi_runtime_classes() -> None:
    ids = allowed_icon_class_ids(load_registry(REGISTRY_PATH))
    assert "FR24_AIRPORT" in ids
    assert "FR24_RESTROOMS" in ids
    assert "FR24_AIRCRAFT_MARKER" in ids
    assert "FR24_UI_CHROME" in ids
    assert len(ids) == 40


def test_malformed_archive_member_returns_fail_instead_of_raising() -> None:
    data = load_registry(REGISTRY_PATH)
    malformed = copy.deepcopy(data)
    malformed["archive_members"].append("not-an-object")

    result = validate_registry(malformed)

    assert result["status"] == "fail"
    assert "archive_members contains a non-object" in result["failures"]


def test_registry_tamper_fails_closed() -> None:
    data = load_registry(REGISTRY_PATH)
    tampered = copy.deepcopy(data)
    row = next(
        row
        for row in tampered["source_manifestations"]
        if row["entity_kind"] == "POI_ICON_SOURCE"
    )
    row["sha256"] = "0" * 64
    result = validate_registry(tampered)
    assert result["status"] == "fail"
    assert any("sha256 does not match archive member" in msg for msg in result["failures"])


def _zip_bytes(entries: list[tuple[str, bytes]], compression: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for path, payload in entries:
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = compression
            archive.writestr(info, payload)
    return buffer.getvalue()


def _minimal_archive_registry(payload: bytes) -> dict:
    import hashlib

    path = "Icon Library/poi_types/example.png"
    member = {
        "path": path,
        "uncompressed_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    member_json = json.dumps(
        [member], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    payload_json = json.dumps(
        [{"uncompressed_size": len(payload), "sha256": member["sha256"]}],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    outer = _zip_bytes([(path, payload)], zipfile.ZIP_STORED)
    return {
        "source_archive": {
            "sha256": hashlib.sha256(outer).hexdigest(),
            "full_member_manifest_sha256": hashlib.sha256(member_json).hexdigest(),
            "payload_multiset_sha256": hashlib.sha256(payload_json).hexdigest(),
        }
    }


def test_archive_equivalence_distinguishes_byte_identity_and_recompression(
    tmp_path: Path,
) -> None:
    payload = b"same icon bytes"
    data = _minimal_archive_registry(payload)
    path = "Icon Library/poi_types/example.png"

    byte_identical = tmp_path / "stored.zip"
    byte_identical.write_bytes(_zip_bytes([(path, payload)], zipfile.ZIP_STORED))
    assert verify_source_archive(byte_identical, data)["status"] == "BYTE_IDENTICAL"

    recompressed = tmp_path / "deflated.zip"
    recompressed.write_bytes(_zip_bytes([(path, payload)], zipfile.ZIP_DEFLATED))
    result = verify_source_archive(recompressed, data)
    assert result["status"] == "PURE_RECOMPRESSION"
    assert result["install_allowed"] is True


def test_archive_equivalence_does_not_treat_path_change_as_same_manifestation(
    tmp_path: Path,
) -> None:
    payload = b"same icon bytes"
    data = _minimal_archive_registry(payload)
    moved = tmp_path / "moved.zip"
    moved.write_bytes(
        _zip_bytes(
            [("Different Folder/example.png", payload)],
            zipfile.ZIP_STORED,
        )
    )
    result = verify_source_archive(moved, data)
    assert result["status"] == "SAME_PAYLOADS_DIFFERENT_PATHS"
    assert result["install_allowed"] is False
