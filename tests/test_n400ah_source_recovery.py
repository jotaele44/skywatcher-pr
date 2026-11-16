"""N400AH source recovery remains evidence-gated and non-promotional."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_PATH = ROOT / "data/flight_tracks/N400AH/source_recovery_attestation.json"
SOURCE_HASHES_PATH = ROOT / "data/flight_tracks/N400AH/source_hashes.csv"
VALIDATOR_PATH = ROOT / "federation/spatial/validate_n400ah_source_recovery.py"

SPEC = importlib.util.spec_from_file_location("n400ah_source_recovery", VALIDATOR_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _attestation() -> dict:
    return json.loads(ATTESTATION_PATH.read_text(encoding="utf-8"))


def test_recovery_attestation_preserves_archive_vs_payload_identity():
    value = _attestation()
    assert value["state"] == "PASS_SOURCE_RECOVERY"
    assert value["dataset_id"] == "N400AH_STRUCTURED_TRACKS_2026Q2_Q3_v1"
    assert (
        value["original_source_archive"]["sha256"]
        == "fa64d13aa3fc32b36b70e84e591b1a3ededb89bb3335e35dda711bb0182b264e"
    )
    assert value["original_source_archive"]["byte_identity_state"] == "UNRESOLVED"
    assert (
        value["recovery_container"]["sha256"]
        == "ace93d7f47041df32a987d5d4afd3a236f07e835dd10fbf1e082d38dceee5998"
    )
    assert value["recovery_container"]["container_comparison_state"] == "DISTINCT_PAYLOADS"
    assert value["in_scope_provider_payloads"] == {
        "expected": 50,
        "matched_byte_identical": 50,
        "missing": 0,
        "divergent": 0,
        "provider_csv": 25,
        "provider_kml": 25,
        "state": "PASS_BYTE_IDENTICAL_SUBSET",
    }


def test_source_ledger_and_point_denominators_close_without_migration_promotion():
    value = _attestation()
    rows = list(
        csv.DictReader(io.StringIO(SOURCE_HASHES_PATH.read_text(encoding="utf-8")))
    )
    assert len(rows) == 50
    assert len({row["path"] for row in rows}) == 50
    roles = {role: sum(row["role"] == role for row in rows) for role in ("provider_csv", "provider_kml")}
    assert roles == {"provider_csv": 25, "provider_kml": 25}

    audit = value["provider_csv_audit"]
    assert audit["track_count"] == 25
    assert audit["point_count"] == 12455
    assert audit["valid_position_count"] == 12455
    assert audit["stable_record_id_count"] == 12455
    assert audit["duplicate_record_id_count"] == 0
    assert audit["unique_provider_timestamp_count"] == 12455
    assert audit["callsign_counts"] == {"N400AH": 12455}
    assert audit["coordinate_evidence_state"] == "VERIFIED_SOURCE_COORDINATE"
    assert audit["source_crs"] == "EPSG:4326"

    migration = value["migration"]
    assert migration["binding_mode_candidate"] == "EXACT_SOURCE_POINT"
    assert migration["source_qualified"] is True
    assert migration["execution_state"] == "INDEPENDENT_NUMERIC_RECOMPUTATION_PASS"
    assert migration["authority_execution_state"] == "NOT_EXECUTED"
    assert (
        migration["ci_reproducibility_state"]
        == "BLOCKED_REDISTRIBUTION_RIGHTS_UNVERIFIED"
    )
    assert migration["source_redistribution_state"] == "UNVERIFIED"
    assert migration["public_source_bytes_committed"] is False
    assert migration["public_derived_coordinate_rows_committed"] is False
    assert migration["promotion_state"] == "CANDIDATE_NOT_CANONICAL"
    assert migration["geometry_copied"] is False


def test_recovered_derived_hashes_match_frozen_ingestion_receipt():
    value = _attestation()["recovered_derived_artifacts"]
    assert value["analysis_receipt.json"] == {
        "bytes": 571,
        "sha256": "f1a1fc3105b139c7c97cb6e5a7030d7643dc1bc57772f606399416cb1de70389",
        "matches_ingestion_receipt": True,
    }
    assert value["tracks.geojson"] == {
        "bytes": 1200867,
        "sha256": "f9092648bababfc80eeeca8bbf34d5309898876247573cec2873f8619bfca9e5",
        "matches_ingestion_receipt": True,
    }


def _write_fixture(tmp_path: Path, *, corrupt: bool = False) -> tuple[Path, Path]:
    csv_data = (
        b"Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction\n"
        b"1,2026-04-09T14:08:39Z,N400AH,\"18.5, -66.0\",100,50,90\n"
    )
    kml_data = b"<kml/>\n"
    csv_sha = mod.sha256_bytes(csv_data)
    if corrupt:
        csv_sha = "0" * 64
    ledger = tmp_path / "source_hashes.csv"
    ledger.write_text(
        "path,role,size_bytes,sha256\n"
        f"track.csv,provider_csv,{len(csv_data)},{csv_sha}\n"
        f"track.kml,provider_kml,{len(kml_data)},{mod.sha256_bytes(kml_data)}\n",
        encoding="utf-8",
    )
    archive = tmp_path / "recovery.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payloads/track.csv", csv_data)
        handle.writestr("payloads/track.kml", kml_data)
    return archive, ledger


def test_validator_accepts_byte_identical_subset_and_preserves_container_state(tmp_path):
    archive, ledger = _write_fixture(tmp_path)
    receipt = mod.validate_recovery(
        archive_path=archive,
        source_hashes_path=ledger,
        prefix="payloads",
    )
    assert receipt["Matched_Source_File_Count"] == 2
    assert receipt["Missing_Source_File_Count"] == 0
    assert receipt["Divergent_Source_File_Count"] == 0
    assert receipt["Point_Count"] == 1
    assert receipt["Coordinate_Evidence_State"] == "VERIFIED_SOURCE_COORDINATE"
    assert receipt["Migration_Execution_State"] == "BLOCKED_SOURCE_NOT_CI_ADDRESSABLE"
    assert receipt["Promotion_State"] == "CANDIDATE_NOT_CANONICAL"


def test_validator_fails_closed_on_member_hash_divergence(tmp_path):
    archive, ledger = _write_fixture(tmp_path, corrupt=True)
    with pytest.raises(mod.RecoveryError, match="closure failed"):
        mod.validate_recovery(
            archive_path=archive,
            source_hashes_path=ledger,
            prefix="payloads",
        )


def test_local_grid_v2_recomputation_receipt_is_closed_and_non_promotional():
    receipt_path = (
        ROOT
        / "data/flight_tracks/N400AH/grid_v2_local_recomputation_receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt["execution_state"] == "INDEPENDENT_NUMERIC_RECOMPUTATION_PASS"
    assert receipt["authority_execution_state"] == "NOT_EXECUTED"
    assert (
        receipt["ci_reproducibility_state"]
        == "BLOCKED_REDISTRIBUTION_RIGHTS_UNVERIFIED"
    )
    assert receipt["promotion_state"] == "CANDIDATE_NOT_CANONICAL"
    assert receipt["geometry_copied"] is False

    rights = receipt["rights"]
    assert rights["repository_visibility"] == "PUBLIC"
    assert rights["provider_source_redistribution_state"] == "UNVERIFIED"
    assert rights["raw_provider_payloads_committed"] is False
    assert rights["derived_coordinate_rows_committed"] is False
    assert rights["per_cell_aggregate_committed"] is False

    subset = receipt["frozen_provider_subset"]
    assert subset["member_count"] == 50
    assert subset["provider_csv"] == 25
    assert subset["provider_kml"] == 25
    assert subset["missing_members"] == 0
    assert subset["divergent_members"] == 0

    recomputation = receipt["independent_numeric_recomputation"]
    assert recomputation["input_record_count"] == 12455
    assert recomputation["binding_row_count"] == 10875
    assert recomputation["state_counts"] == {
        "INTERIOR": 10875,
        "OUTSIDE": 1580,
        "EDGE_SHARED": 0,
        "CORNER_SHARED": 0,
    }
    assert recomputation["unique_bound_l2_cell_count"] == 3211
    assert recomputation["boundary_snap_record_count"] == 0
    assert recomputation["row_conservation_state"] == "PASS"

    assert receipt["deterministic_local_source_bundle"]["public_repository_path"] is None
    assert receipt["local_aggregate_artifact"]["public_repository_path"] is None
