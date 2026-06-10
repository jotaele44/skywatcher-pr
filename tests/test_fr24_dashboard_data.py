"""Tests for fr24_dashboard_data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import fr24.dashboard_data as mod



def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "queue.csv", tmp_path / "summary.json", tmp_path / "out.json"


def test_empty_inputs_produce_valid_payload(tmp_paths):
    queue_csv, summary_json, output_json = tmp_paths
    queue_csv.write_text("", encoding="utf-8")
    summary = mod.run(queue_csv, summary_json, output_json)
    assert summary["row_count"] == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["rows"] == []
    assert payload["policy"] == "candidate_only_no_auto_confirmation"
    assert payload["dashboard_data_version"] == mod.DASHBOARD_DATA_VERSION
    assert list(payload["allowed_queue_statuses"]) == list(mod.ALLOWED_QUEUE_STATUSES)
    assert payload["local_state_schema_version"] == mod.LOCAL_STATE_SCHEMA_VERSION
    assert payload["local_state_policy"] == mod.LOCAL_STATE_POLICY
    assert summary["allowed_queue_statuses"] == list(mod.ALLOWED_QUEUE_STATUSES)
    assert summary["local_state_schema_version"] == mod.LOCAL_STATE_SCHEMA_VERSION
    assert summary["local_state_policy"] == mod.LOCAL_STATE_POLICY
    assert payload["prohibited_label_dropped"] == 0


def test_rows_pass_through_with_normalized_integers(tmp_paths):
    queue_csv, summary_json, output_json = tmp_paths
    write_csv(queue_csv, [
        {
            "candidate_id": "fused::fr24_001.png",
            "image_path": "/data/screens/fr24_001.png",
            "image_name": "fr24_001.png",
            "priority_score": "100",
            "priority_tier": "1",
            "queue_source": "field_selection_review",
            "queue_status": "dashboard_review_open",
            "review_status": "field_disagreement_review",
            "selection_status": "field_disagreement_review",
            "dedup_status": "dedup_kept_primary",
            "confirmation_status": "not_confirmed",
            "conflict_count": "3",
        }
    ])
    summary_json.write_text(json.dumps({"queue_rows": 1}), encoding="utf-8")
    mod.run(queue_csv, summary_json, output_json)
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1
    row = payload["rows"][0]
    assert row["candidate_id"] == "fused::fr24_001.png"
    assert row["priority_score"] == 100
    assert row["priority_tier"] == 1
    assert row["conflict_count"] == 3
    assert row["confirmation_status"] == "not_confirmed"
    assert payload["upstream_summary"] == {"queue_rows": 1}
    assert payload["tier_counts"] == {"1": 1} or payload["tier_counts"] == {1: 1}


def test_prohibited_label_row_dropped_and_counted(tmp_paths):
    queue_csv, summary_json, output_json = tmp_paths
    write_csv(queue_csv, [
        {
            "candidate_id": "fused::clean.png",
            "image_path": "/data/screens/clean.png",
            "image_name": "clean.png",
            "priority_score": "100",
            "priority_tier": "1",
            "queue_source": "field_selection_review",
            "queue_status": "dashboard_review_open",
            "review_status": "field_disagreement_review",
            "selection_status": "field_disagreement_review",
            "confirmation_status": "not_confirmed",
        },
        {
            "candidate_id": "fused::bad.png",
            "image_path": "/data/screens/bad.png",
            "image_name": "bad.png",
            "priority_score": "60",
            "priority_tier": "3",
            "queue_source": "field_selection_review",
            "queue_status": "dashboard_review_open",
            "review_status": "manual_review_required",
            "selection_status": "selected_with_review_required",
            # Defense-in-depth: this should never appear from the pipeline,
            # but if it does the exporter must drop it.
            "confirmation_status": "confirmed_aircraft_event",
        },
    ])
    mod.run(queue_csv, summary_json, output_json)
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1
    assert payload["prohibited_label_dropped"] == 1
    assert payload["rows"][0]["candidate_id"] == "fused::clean.png"


def test_payload_never_emits_prohibited_label_in_status_fields(tmp_paths):
    queue_csv, summary_json, output_json = tmp_paths
    write_csv(queue_csv, [
        {
            "candidate_id": "fused::a.png",
            "image_name": "a.png",
            "priority_score": "100",
            "priority_tier": "1",
            "queue_source": "field_selection_review",
            "queue_status": "dashboard_review_open",
            "review_status": "field_disagreement_review",
            "confirmation_status": "not_confirmed",
        }
    ])
    mod.run(queue_csv, summary_json, output_json)
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    status_fields = ("confirmation_status", "dedup_status", "selection_status", "review_status", "queue_status")
    for row in payload["rows"]:
        for field in status_fields:
            assert row.get(field, "") not in mod.PROHIBITED_LABELS


def test_allowed_queue_statuses_exclude_prohibited_labels():
    allowed = set(mod.ALLOWED_QUEUE_STATUSES)
    assert allowed
    assert allowed.isdisjoint(mod.PROHIBITED_LABELS)
    assert "dashboard_review_open" in allowed
    assert "dashboard_review_accepted_after_manual_review" in allowed


def test_missing_summary_file_does_not_break_export(tmp_paths):
    queue_csv, summary_json, output_json = tmp_paths
    write_csv(queue_csv, [
        {
            "candidate_id": "fused::a.png",
            "image_name": "a.png",
            "priority_score": "60",
            "priority_tier": "3",
            "queue_source": "field_selection_review",
            "queue_status": "dashboard_review_open",
            "review_status": "manual_review_required",
            "confirmation_status": "not_confirmed",
        }
    ])
    # summary_json deliberately not created
    summary = mod.run(queue_csv, summary_json, output_json)
    assert summary["row_count"] == 1
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["upstream_summary"] == {}
