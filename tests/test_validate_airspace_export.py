import csv
import json
import shutil
from pathlib import Path

from scripts.validate_airspace_export import validate_capture_bbox, validate_package

PACKAGE_DIR = Path("exports/examples/synthetic_airspace_package")


def test_synthetic_package_passes_in_test_mode():
    assert validate_package(PACKAGE_DIR, "test") == []


def test_synthetic_package_fails_in_production_mode():
    errors = validate_package(PACKAGE_DIR, "production")
    assert errors
    assert any("synthetic rows are not allowed" in error for error in errors)


def test_production_rejects_synthetic_csv_even_if_geojson_is_marked_live(tmp_path):
    package = tmp_path / "package"
    shutil.copytree(PACKAGE_DIR, package)

    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mode"] = "production"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    geojson_path = package / "observations.geojson"
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    for feature in geojson["features"]:
        feature["properties"]["synthetic"] = False
    geojson_path.write_text(json.dumps(geojson), encoding="utf-8")

    sources_path = package / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    for source in sources:
        source["provenance_status"] = "operator_capture"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")

    csv_path = package / "observations.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    synthetic_ids = [row["observation_id"] for row in rows]
    for row in rows:
        row["synthetic"] = "true"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    errors = validate_package(package, "production")

    assert any(
        f"{observation_id}: synthetic CSV rows are not allowed" in error
        for observation_id in synthetic_ids
        for error in errors
    )


def test_nonempty_geojson_cannot_pass_with_empty_csv(tmp_path):
    package = tmp_path / "package"
    shutil.copytree(PACKAGE_DIR, package)

    with (package / "observations.csv").open(encoding="utf-8", newline="") as handle:
        fieldnames = csv.DictReader(handle).fieldnames
    with (package / "observations.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fieldnames).writeheader()

    errors = validate_package(package, "test")

    assert "observations.csv IDs do not match observations.geojson" in errors


def test_capture_bbox_with_non_object_json_is_rejected():
    assert validate_capture_bbox("[]") == ["capture_bbox_geojson must be a JSON object"]


def test_requested_mode_must_match_manifest_mode():
    errors = validate_package(PACKAGE_DIR, "production")
    assert "manifest mode must match requested mode (production)" in errors
