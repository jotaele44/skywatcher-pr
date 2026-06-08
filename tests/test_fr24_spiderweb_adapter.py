"""Tests for fr24_spiderweb_adapter."""

import json
from pathlib import Path

import pytest

from fr24.spiderweb_adapter import (
    ADAPTER_VERSION,
    PROHIBITED_LABELS,
    is_intake_eligible,
    map_to_flight_event,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _make_export_record(
    image_name: str = "img_001.png",
    selection_status: str = "selected_candidate",
    review_status: str = "fused_candidate",
    dashboard_status: str = "",
    callsign: str = "N1234A",
    origin_code: str = "SJU",
    destination_code: str = "BQN",
    barometric_altitude_ft: str = "8500",
    ground_speed_mph: str = "185",
    playback_date: str = "2023-01-15",
    playback_time: str = "10:22:33",
    playback_timezone: str = "-04:00",
    confirmation_status: str = "not_confirmed",
    dedup_status: str = "dedup_kept_primary",
) -> dict:
    return {
        "candidate_id": f"fused::{image_name}",
        "image_path": f"data/Flight Logs/{image_name}",
        "image_name": image_name,
        "callsign_or_label": callsign,
        "operator": "American Airlines",
        "aircraft_type": "Boeing C-17A",
        "registration": "N1234A",
        "origin_code": origin_code,
        "destination_code": destination_code,
        "barometric_altitude_ft": barometric_altitude_ft,
        "ground_speed_mph": ground_speed_mph,
        "flight_status": "departed_candidate",
        "playback_date": playback_date,
        "playback_time": playback_time,
        "playback_timezone": playback_timezone,
        "review_status": review_status,
        "selection_status": selection_status,
        "dedup_status": dedup_status,
        "dashboard_status": dashboard_status,
        "confirmation_status": confirmation_status,
        "selected_field_disagreements": "",
        "missing_selected_fields": "",
        "conflict_count": "0",
        "export_version": "fr24_selected_export_v0.1.0",
        "fusion_version": "fr24_ocr_fusion_v0.1.0",
        "field_select_version": "fr24_field_select_v0.1.0",
        "dedup_version": "fr24_fused_dedup_v0.1.0",
        "parser_version": "1.0.0",
    }


def _run(tmp_path: Path, records: list) -> dict:
    export_jsonl = tmp_path / "export.jsonl"
    _write_jsonl(export_jsonl, records)
    return run(
        export_jsonl=export_jsonl,
        output_jsonl=tmp_path / "intake.jsonl",
        hold_jsonl=tmp_path / "hold.jsonl",
        summary_json=tmp_path / "summary.json",
    )


# ---------------------------------------------------------------------------
# TestFieldMapping
# ---------------------------------------------------------------------------

class TestFieldMapping:
    def test_maps_candidate_id_to_flight_id(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["flight_id"] == "fused::img_001.png"

    def test_flight_id_falls_back_to_image_name(self):
        row = _make_export_record()
        row["candidate_id"] = ""
        mapped = map_to_flight_event(row)
        assert mapped["flight_id"].startswith("fr24::")
        assert "img_001.png" in mapped["flight_id"]

    def test_maps_callsign_or_label_to_callsign(self):
        row = _make_export_record(callsign="AAL123")
        mapped = map_to_flight_event(row)
        assert mapped["callsign"] == "AAL123"

    def test_maps_optional_flight_fields(self):
        row = _make_export_record(
            origin_code="SJU",
            destination_code="BQN",
            barometric_altitude_ft="8500",
            ground_speed_mph="185",
        )
        mapped = map_to_flight_event(row)
        assert mapped["origin_airport"] == "SJU"
        assert mapped["destination_airport"] == "BQN"
        assert mapped["max_altitude_ft"] == 8500
        assert mapped["avg_speed_mph"] == 185.0
        assert mapped["aircraft_type"] == "Boeing C-17A"
        assert mapped["operator"] == "American Airlines"

    def test_takeoff_time_combines_date_time_tz(self):
        row = _make_export_record(
            playback_date="2023-01-15",
            playback_time="10:22:33",
            playback_timezone="-04:00",
        )
        mapped = map_to_flight_event(row)
        assert mapped["takeoff_time"] == "2023-01-15T10:22:33-04:00"

    def test_takeoff_time_none_when_no_date(self):
        row = _make_export_record(playback_date="", playback_time="10:22:33")
        mapped = map_to_flight_event(row)
        assert mapped["takeoff_time"] is None

    def test_confirmation_status_is_not_confirmed(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["confirmation_status"] == "not_confirmed"

    def test_intake_status_is_candidate_intake_ready(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["intake_status"] == "candidate_intake_ready"

    def test_source_adapter_version_is_set(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["source_adapter"] == ADAPTER_VERSION

    def test_provenance_fields_preserved(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["source_image_path"] == "data/Flight Logs/img_001.png"
        assert mapped["export_version"] == "fr24_selected_export_v0.1.0"
        assert mapped["fusion_version"] == "fr24_ocr_fusion_v0.1.0"

    def test_num_screenshots_is_one(self):
        row = _make_export_record()
        mapped = map_to_flight_event(row)
        assert mapped["num_screenshots"] == 1


# ---------------------------------------------------------------------------
# TestGating
# ---------------------------------------------------------------------------

class TestGating:
    def test_selected_candidate_passes_gate(self):
        row = _make_export_record(selection_status="selected_candidate")
        assert is_intake_eligible(row) is True

    def test_dashboard_accepted_passes_gate(self):
        row = _make_export_record(
            selection_status="selected_with_review_required",
            dashboard_status="dashboard_review_accepted_after_manual_review",
        )
        assert is_intake_eligible(row) is True

    def test_review_required_goes_to_hold_queue(self, tmp_path):
        records = [
            _make_export_record("img_001.png", selection_status="selected_candidate"),
            _make_export_record("img_002.png", selection_status="selected_with_review_required"),
            _make_export_record("img_003.png", selection_status="field_disagreement_review"),
        ]
        _run(tmp_path, records)

        intake = _read_jsonl(tmp_path / "intake.jsonl")
        hold = _read_jsonl(tmp_path / "hold.jsonl")
        assert len(intake) == 1
        assert len(hold) == 2

    def test_hold_record_carries_hold_reason(self, tmp_path):
        records = [_make_export_record(selection_status="field_disagreement_review")]
        _run(tmp_path, records)
        hold = _read_jsonl(tmp_path / "hold.jsonl")
        assert hold[0]["hold_reason"] == "selection_status_not_passthrough"

    def test_hold_record_is_not_confirmed(self, tmp_path):
        records = [_make_export_record(selection_status="manual_review_required")]
        _run(tmp_path, records)
        for row in _read_jsonl(tmp_path / "hold.jsonl"):
            assert row["confirmation_status"] == "not_confirmed"

    def test_no_prohibited_labels_in_output(self, tmp_path):
        records = [_make_export_record()]
        _run(tmp_path, records)
        for rec in _read_jsonl(tmp_path / "intake.jsonl"):
            for value in rec.values():
                assert str(value) not in PROHIBITED_LABELS, (
                    f"Prohibited label '{value}' found in intake record"
                )

    def test_row_with_prohibited_label_dropped(self, tmp_path):
        records = [
            _make_export_record("img_001.png"),
            _make_export_record("img_002.png", confirmation_status="confirmed"),
        ]
        summary = _run(tmp_path, records)
        assert summary["prohibited_label_dropped"] == 1
        assert summary["intake_records"] == 1


# ---------------------------------------------------------------------------
# TestRun
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_produces_all_output_files(self, tmp_path):
        records = [_make_export_record()]
        _run(tmp_path, records)
        assert (tmp_path / "intake.jsonl").exists()
        assert (tmp_path / "hold.jsonl").exists()
        assert (tmp_path / "summary.json").exists()

    def test_run_intake_count_matches_eligible_records(self, tmp_path):
        records = [
            _make_export_record(f"img_{i:03d}.png", selection_status="selected_candidate")
            for i in range(4)
        ]
        records.append(_make_export_record("img_004.png", selection_status="manual_review_required"))
        summary = _run(tmp_path, records)
        assert summary["intake_records"] == 4
        assert summary["hold_records"] == 1

    def test_run_summary_has_expected_keys(self, tmp_path):
        summary = _run(tmp_path, [_make_export_record()])
        for key in (
            "total_input_records", "intake_records", "hold_records",
            "prohibited_label_dropped", "adapter_version", "policy",
            "selection_status_counts", "intake_status_counts",
        ):
            assert key in summary, f"Missing key '{key}' in summary"

    def test_run_summary_policy_is_candidate_only(self, tmp_path):
        summary = _run(tmp_path, [])
        assert summary["policy"] == "candidate_only_no_auto_confirmation"

    def test_empty_input_writes_empty_outputs(self, tmp_path):
        summary = _run(tmp_path, [])
        assert summary["intake_records"] == 0
        assert summary["hold_records"] == 0
        assert _read_jsonl(tmp_path / "intake.jsonl") == []
        assert _read_jsonl(tmp_path / "hold.jsonl") == []

    def test_invalid_jsonl_line_skipped_gracefully(self, tmp_path):
        export_jsonl = tmp_path / "export.jsonl"
        with export_jsonl.open("w") as f:
            f.write(json.dumps(_make_export_record()) + "\n")
            f.write("not valid json\n")
            f.write(json.dumps(_make_export_record("img_002.png")) + "\n")
        summary = run(
            export_jsonl,
            tmp_path / "intake.jsonl",
            tmp_path / "hold.jsonl",
            tmp_path / "summary.json",
        )
        # 2 valid records parsed; bad line silently skipped
        assert summary["total_input_records"] == 2
