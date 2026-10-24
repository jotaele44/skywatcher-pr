"""Real immutable producer input plus positive/negative transport compatibility."""

import copy
import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from skywatcher.core.ionosphere import build_glotec_package, canonical_bytes
from skywatcher.core.pitirre_observation import ObservationAdapterError

ROOT = Path(__file__).resolve().parents[1]


def capture():
    with zipfile.ZipFile(ROOT / "tests/fixtures/ionosphere/glotec_20261023T163500Z.zip") as z:
        receipt = json.loads(z.read("receipt.json"))
        source = receipt["attempts"][-1]
        return z.read(source["sha256"] + ".bin"), source["url"], receipt["retrieved_utc"]


def test_real_producer_preserves_every_selected_row_and_conserves_counts():
    raw, url, stamp = capture()
    result = build_glotec_package(raw, url, stamp)
    original = json.loads(raw)
    validator = Draft202012Validator(
        json.loads((ROOT / "schemas/pitirre_observation.v2.schema.json").read_text())
    )
    ids = []
    assert result["source_count"] == 5184
    assert result["retained_count"] == 6
    assert result["excluded_count"] == 5178
    assert result["retained_count"] + result["excluded_count"] == result["source_count"]
    for row in result["records"]:
        validator.validate(row)
        payload = row["payload"]
        assert (
            payload["raw_feature"] == original["features"][payload["source_manifest"]["row_index"]]
        )
        assert row["evidence"]["operational_use_allowed"] is False
        assert row["domain"] == "SPACE"
        ids.append(row["observation_id"])
    assert len(set(ids)) == 6
    assert canonical_bytes(result) == canonical_bytes(build_glotec_package(raw, url, stamp))
    mutation = copy.deepcopy(result["records"][0])
    mutation["domain"] = "AIR"
    with pytest.raises(ValidationError):
        validator.validate(mutation)
    mutation = copy.deepcopy(result["records"][0])
    mutation["evidence"]["operational_use_allowed"] = True
    with pytest.raises(ValidationError):
        validator.validate(mutation)
    old = Draft202012Validator(
        json.loads((ROOT / "schemas/pitirre_observation.v1.schema.json").read_text())
    )
    with pytest.raises(ValidationError):
        old.validate(result["records"][0])


def test_missing_duplicate_nodes_bad_units_and_timestamps_fail_closed():
    raw, url, stamp = capture()
    for defect in ("missing", "duplicate", "units", "coordinates"):
        value = json.loads(raw)
        if defect == "missing":
            value["features"].pop()
        elif defect == "duplicate":
            value["features"][-1] = copy.deepcopy(value["features"][0])
        elif defect == "units":
            value["metadata"]["variables"]["tec"]["units"] = "unknown"
        else:
            value["features"][0]["geometry"]["coordinates"][0] = None
        with pytest.raises(ObservationAdapterError):
            build_glotec_package(json.dumps(value).encode(), url, stamp)
    with pytest.raises(ObservationAdapterError):
        build_glotec_package(raw, url, "2020-01-01T00:00:00Z")
    with pytest.raises(ObservationAdapterError):
        build_glotec_package(raw, "https://example.org/aliased", stamp)


def test_filename_epoch_conflict_is_rejected():
    raw, url, stamp = capture()
    with pytest.raises(ObservationAdapterError, match="epoch disagree"):
        build_glotec_package(raw, url.replace("163500", "164500"), stamp)


def test_committed_export_is_exact_producer_output_and_source_code_binding():
    import hashlib

    raw, url, stamp = capture()
    package = canonical_bytes(build_glotec_package(raw, url, stamp))
    assert (ROOT / "exports/ionosphere/glotec_context.package.json").read_bytes() == package
    manifest = json.loads((ROOT / "exports/ionosphere/manifest.json").read_text())
    assert hashlib.sha256(package).hexdigest() == manifest["package_sha256"]
    code = (ROOT / "src/skywatcher/core/ionosphere.py").read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(code)).encode() + b"\0" + code).hexdigest()
    assert blob == manifest["producer_module_git_blob"]
