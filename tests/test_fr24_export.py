"""Tests for fr24_selected_export and fr24_dashboard_queue."""

import csv
import json
from pathlib import Path

import pytest

from fr24.selected_export import (
    EXPORT_VERSION,
    PROHIBITED_LABELS,
    has_prohibited_label,
    run as export_run,
)
from fr24.dashboard_queue import (
    DASHBOARD_QUEUE_VERSION,
    TIER_FIELD_DISAGREEMENT,
    TIER_FUSION_CONFLICT,
    TIER_MANUAL_REVIEW,
    TIER_DUPLICATE_REVIEW,
    row_identity,
    run as dashboard_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list, fieldnames: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _make_selected_row(
    image_path: str = "data/img_001.png",
    selection_status: str = "selected_candidate",
    review_status: str = "fused_candidate",
    confirmation_status: str = "not_confirmed",
    dedup_status: str = "dedup_kept_primary",
) -> dict:
    return {
        "candidate_id": f"fused::{Path(image_path).name}",
        "image_path": image_path,
        "image_name": Path(image_path).name,
        "callsign_or_label": "N1234A",
        "callsign_or_label_selected_source": "whole_image",
        "operator": "",
        "operator_selected_source": "",
        "aircraft_type": "Boeing C-17A",
        "aircraft_type_selected_source": "whole_image",
        "registration": "N1234A",
        "registration_selected_source": "whole_image",
        "origin_code": "BQN",
        "origin_code_selected_source": "whole_image",
        "destination_code": "SJU",
        "destination_code_selected_source": "whole_image",
        "barometric_altitude_ft": "8500",
        "barometric_altitude_ft_selected_source": "whole_image",
        "ground_speed_mph": "185",
        "ground_speed_mph_selected_source": "whole_image",
        "flight_status": "",
        "flight_status_selected_source": "",
        "elapsed_departed": "",
        "elapsed_departed_selected_source": "",
        "elapsed_arrived": "",
        "elapsed_arrived_selected_source": "",
        "playback_date": "",
        "playback_date_selected_source": "",
        "playback_time": "",
        "playback_time_selected_source": "",
        "playback_timezone": "",
        "playback_timezone_selected_source": "",
        "review_status": review_status,
        "selection_status": selection_status,
        "dedup_status": dedup_status,
        "confirmation_status": confirmation_status,
        "selected_field_disagreements": "",
        "missing_selected_fields": "",
        "conflict_count": "0",
        "whole_confidence": "0.75",
        "region_confidence": "0.70",
        "fusion_version": "fr24_ocr_fusion_v0.1.0",
        "field_select_version": "fr24_field_select_v0.1.0",
        "dedup_version": "fr24_fused_dedup_v0.1.0",
        "parser_version": "1.0.0",
    }


SELECTED_FIELDS = list(_make_selected_row().keys())


def _run_export(tmp_path: Path, rows: list) -> dict:
    selected_csv = tmp_path / "selected.csv"
    _write_csv(selected_csv, rows, SELECTED_FIELDS)
    return export_run(
        selected_csv=selected_csv,
        field_review_csv=tmp_path / "field_review.csv",
        duplicate_review_csv=tmp_path / "dup_review.csv",
        ledger_csv=tmp_path / "ledger.csv",
        output_csv=tmp_path / "export.csv",
        output_jsonl=tmp_path / "export.jsonl",
        summary_json=tmp_path / "summary.json",
        source_manifest_json=tmp_path / "manifest.json",
    )


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------

class TestExport:
    def test_exports_all_selected_rows(self, tmp_path):
        rows = [_make_selected_row(f"data/img_{i:03d}.png") for i in range(5)]
        summary = _run_export(tmp_path, rows)

        exported = _read_csv(tmp_path / "export.csv")
        assert len(exported) == 5
        assert summary["exported_rows"] == 5

    def test_output_jsonl_has_one_record_per_row(self, tmp_path):
        rows = [_make_selected_row(f"data/img_{i:03d}.png") for i in range(3)]
        _run_export(tmp_path, rows)

        lines = [l for l in (tmp_path / "export.jsonl").read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        assert all(json.loads(l).get("image_path") for l in lines)

    def test_confirmation_status_is_not_confirmed(self, tmp_path):
        rows = [_make_selected_row()]
        _run_export(tmp_path, rows)

        for row in _read_csv(tmp_path / "export.csv"):
            assert row["confirmation_status"] == "not_confirmed"

    def test_export_version_is_set(self, tmp_path):
        rows = [_make_selected_row()]
        _run_export(tmp_path, rows)

        for row in _read_csv(tmp_path / "export.csv"):
            assert row["export_version"] == EXPORT_VERSION

    def test_source_csv_path_field_is_set(self, tmp_path):
        rows = [_make_selected_row()]
        _run_export(tmp_path, rows)

        for row in _read_csv(tmp_path / "export.csv"):
            assert "source_csv_path" in row and row["source_csv_path"]

    def test_source_manifest_contains_policy(self, tmp_path):
        rows = [_make_selected_row()]
        _run_export(tmp_path, rows)

        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["policy"] == "candidate_only_no_auto_confirmation"
        assert manifest["export_version"] == EXPORT_VERSION

    def test_no_prohibited_labels(self, tmp_path):
        rows = [_make_selected_row()]
        _run_export(tmp_path, rows)

        for row in _read_csv(tmp_path / "export.csv"):
            for value in row.values():
                assert value not in PROHIBITED_LABELS, f"Prohibited label '{value}' found"

    def test_drops_row_with_prohibited_label(self, tmp_path):
        rows = [
            _make_selected_row("data/img_001.png"),
            _make_selected_row("data/img_002.png", confirmation_status="confirmed"),
        ]
        summary = _run_export(tmp_path, rows)

        assert summary["exported_rows"] == 1
        assert summary["prohibited_label_dropped"] == 1

    def test_empty_input_writes_empty_outputs(self, tmp_path):
        summary = _run_export(tmp_path, [])

        assert summary["exported_rows"] == 0
        exported = _read_csv(tmp_path / "export.csv")
        assert exported == []


# ---------------------------------------------------------------------------
# TestDashboardQueue
# ---------------------------------------------------------------------------

def _make_field_review_row(
    image_path: str = "data/img_001.png",
    review_status: str = "manual_review_required",
    selection_status: str = "selected_with_review_required",
    conflict_count: str = "0",
    selected_field_disagreements: str = "",
) -> dict:
    return {
        "image_path": image_path,
        "image_name": Path(image_path).name,
        "candidate_id": f"fused::{Path(image_path).name}",
        "review_status": review_status,
        "selection_status": selection_status,
        "dedup_status": "dedup_kept_primary",
        "confirmation_status": "not_confirmed",
        "conflict_count": conflict_count,
        "selected_field_disagreements": selected_field_disagreements,
        "whole_confidence": "0.75",
        "region_confidence": "0.70",
    }


FIELD_REVIEW_FIELDS = list(_make_field_review_row().keys())


def _run_dashboard(
    tmp_path: Path,
    field_review_rows: list,
    dup_review_rows=None,
    selected_rows=None,
) -> dict:
    field_review_csv = tmp_path / "field_review.csv"
    dup_review_csv = tmp_path / "dup_review.csv"
    selected_csv = tmp_path / "selected.csv"
    ocr_error_csv = tmp_path / "ocr_error.csv"  # non-existent is fine
    _write_csv(field_review_csv, field_review_rows, FIELD_REVIEW_FIELDS)
    if dup_review_rows is not None:
        _write_csv(dup_review_csv, dup_review_rows, FIELD_REVIEW_FIELDS)
    if selected_rows is not None:
        _write_csv(selected_csv, selected_rows, SELECTED_FIELDS)
    return dashboard_run(
        selected_csv=selected_csv,
        field_review_csv=field_review_csv,
        duplicate_review_csv=dup_review_csv,
        ocr_error_csv=ocr_error_csv,
        output_csv=tmp_path / "queue.csv",
        summary_json=tmp_path / "summary.json",
    )


class TestDashboardQueue:
    def test_field_disagreement_ranks_first(self, tmp_path):
        rows = [
            _make_field_review_row("data/img_001.png", review_status="field_disagreement_review",
                                   selection_status="field_disagreement_review"),
            _make_field_review_row("data/img_002.png", review_status="manual_review_required"),
        ]
        _run_dashboard(tmp_path, rows)

        queue = _read_csv(tmp_path / "queue.csv")
        assert queue[0]["image_path"] == "data/img_001.png"
        assert int(queue[0]["priority_tier"]) == TIER_FIELD_DISAGREEMENT

    def test_fusion_conflict_ranks_above_manual(self, tmp_path):
        rows = [
            _make_field_review_row("data/img_001.png", review_status="manual_review_required"),
            _make_field_review_row("data/img_002.png", review_status="fusion_conflict_review"),
        ]
        _run_dashboard(tmp_path, rows)

        queue = _read_csv(tmp_path / "queue.csv")
        tiers = [int(r["priority_tier"]) for r in queue]
        fusion_idx = next(i for i, r in enumerate(queue) if r["review_status"] == "fusion_conflict_review")
        manual_idx = next(i for i, r in enumerate(queue) if r["review_status"] == "manual_review_required")
        assert fusion_idx < manual_idx

    def test_dedup_duplicate_included(self, tmp_path):
        field_rows = [_make_field_review_row("data/img_001.png")]
        dup_rows = [_make_field_review_row("data/img_002.png", review_status="fusion_conflict_review")]
        _run_dashboard(tmp_path, field_rows, dup_review_rows=dup_rows)

        queue = _read_csv(tmp_path / "queue.csv")
        paths = {r["image_path"] for r in queue}
        assert "data/img_002.png" in paths

    def test_dashboard_status_is_open(self, tmp_path):
        rows = [_make_field_review_row()]
        _run_dashboard(tmp_path, rows)

        for row in _read_csv(tmp_path / "queue.csv"):
            assert row["queue_status"] == "dashboard_review_open"

    def test_no_prohibited_labels_in_queue(self, tmp_path):
        rows = [
            _make_field_review_row("data/img_001.png", review_status="field_disagreement_review"),
            _make_field_review_row("data/img_002.png", review_status="manual_review_required"),
        ]
        _run_dashboard(tmp_path, rows)

        prohibited = {
            "confirmed", "confirmed_aircraft_event", "confirmed_anomaly",
            "confirmed_route", "verified_event", "validated_aircraft_event",
        }
        for row in _read_csv(tmp_path / "queue.csv"):
            for value in row.values():
                assert value not in prohibited, f"Prohibited label '{value}' in queue"

    def test_empty_inputs_returns_empty_queue(self, tmp_path):
        summary = _run_dashboard(tmp_path, [])

        assert summary["queue_rows"] == 0
        assert _read_csv(tmp_path / "queue.csv") == []

    def test_row_identity_uses_fallback_chain(self):
        # image_path takes priority
        assert row_identity({"image_path": "img.png", "image_name": "img.png"}).startswith("image_path::")
        # falls back to image_name when image_path is empty
        assert row_identity({"image_path": "", "image_name": "img.png", "candidate_id": "fused::img"}).startswith("image_name::")
        # falls back to candidate_id when both empty
        assert row_identity({"image_path": "", "image_name": "", "candidate_id": "fused::img"}).startswith("candidate_id::")
        # last-resort fallback when all three are missing
        result = row_identity({"image_path": "", "image_name": "", "candidate_id": ""})
        assert result.startswith("unidentified::")
