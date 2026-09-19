import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
VALIDATOR = ROOT / "scripts" / "validate_flight_corpus_v4_import.py"
BLOCKED = [
    "N2JJ_RAW_SOURCE_LINEAGE",
    "COMPLETE_ISLANDWIDE_ELECTRICAL_GRID_DENOMINATOR",
    "HBAL_CROSS_IDENTIFIER_IDENTITY",
]


def base_manifest(tmp_path):
    data = tmp_path / "rows.csv"
    data.write_text("a\n1\n", encoding="utf-8")
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    return {
        "schema_version": "skywatcher.flight_corpus.import.v1",
        "corpus_version": "V4",
        "certification_state": "PROVISIONAL",
        "source_artifact": {"sha256": "0" * 64},
        "denominators": {
            "nonempty_logical_records": 696,
            "single_point_exclusions": 11,
            "trajectory_eligible": 685,
            "unordered_pair_denominator": 234270,
        },
        "datasets": [{
            "dataset_id": "x",
            "path": "rows.csv",
            "sha256": digest,
            "role": "RELATIONAL_LEDGER",
            "lineage_state": "PASS",
        }],
        "blocked": list(BLOCKED),
    }


def run(tmp_path, manifest):
    path = tmp_path / "import_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_fixture_passes(tmp_path):
    assert run(tmp_path, base_manifest(tmp_path)).returncode == 0


def test_hash_mismatch_fails(tmp_path):
    m = base_manifest(tmp_path)
    m["datasets"][0]["sha256"] = "f" * 64
    assert run(tmp_path, m).returncode != 0


def test_denominator_mismatch_fails(tmp_path):
    m = base_manifest(tmp_path)
    m["denominators"]["trajectory_eligible"] = 686
    assert run(tmp_path, m).returncode != 0


def test_blocker_removal_fails(tmp_path):
    m = base_manifest(tmp_path)
    m["blocked"].remove("N2JJ_RAW_SOURCE_LINEAGE")
    assert run(tmp_path, m).returncode != 0


def test_duplicate_dataset_id_fails(tmp_path):
    m = base_manifest(tmp_path)
    m["datasets"].append(copy.deepcopy(m["datasets"][0]))
    m["datasets"][1]["path"] = "other.csv"
    (tmp_path / "other.csv").write_text("a\n1\n", encoding="utf-8")
    m["datasets"][1]["sha256"] = hashlib.sha256((tmp_path / "other.csv").read_bytes()).hexdigest()
    assert run(tmp_path, m).returncode != 0


def test_duplicate_path_fails(tmp_path):
    m = base_manifest(tmp_path)
    second = copy.deepcopy(m["datasets"][0])
    second["dataset_id"] = "y"
    m["datasets"].append(second)
    assert run(tmp_path, m).returncode != 0


def test_missing_file_fails(tmp_path):
    m = base_manifest(tmp_path)
    m["datasets"][0]["path"] = "missing.csv"
    assert run(tmp_path, m).returncode != 0
