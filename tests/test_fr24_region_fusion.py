"""Tests for FR24 region OCR parsing, fusion, batch runner, and batch status."""

import csv
import json
import textwrap
from pathlib import Path

import pytest

from fr24.region_parse import parse_jsonl as region_parse_jsonl, parse_region_record
from fr24.ocr_fusion import run_fusion, fuse_records
from fr24.batch_run import run_batch
from fr24.batch_status import read_ledger, summarize
from fr24.review_queue_builder import build_review_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _write_csv(path: Path, rows: list, fieldnames: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


REGION_RECORD_FULL = {
    "image_path": "data/img_001.png",
    "image_name": "img_001.png",
    "sidecar_path": "data/IMG_001.json",
    "sidecar_title": "IMG_001.PNG",
    "match_band": "strong",
    "resolved_status": "matched_primary",
    "ocr_region": "panel",
    "region_type": "panel",
    "region_bbox": {"x": 0, "y": 553, "w": 1024, "h": 215},
    "ocr_text": "N1234A (AAL) American Airlines Boeing C-17A Globemaster III BQN SJU BAROMETRIC ALT 8500 ft GROUND SPEED 185 mph",
    "ocr_char_count": 112,
    "ocr_status": "complete",
    "parser_version": "1.0.0",
    "error": "",
}

REGION_RECORD_CALLSIGN = {
    **REGION_RECORD_FULL,
    "ocr_region": "callsign",
    "region_type": "callsign",
    "region_bbox": {"x": 20, "y": 579, "w": 256, "h": 64},
    "ocr_text": "N1234A (AAL)",
    "ocr_char_count": 12,
}

REGION_RECORD_ALTITUDE = {
    **REGION_RECORD_FULL,
    "ocr_region": "altitude",
    "region_type": "altitude",
    "region_bbox": {"x": 20, "y": 643, "w": 153, "h": 54},
    "ocr_text": "8500 ft",
    "ocr_char_count": 7,
}

REGION_RECORD_SPEED = {
    **REGION_RECORD_FULL,
    "ocr_region": "speed",
    "region_type": "speed",
    "ocr_text": "185 mph",
    "ocr_char_count": 7,
}

REGION_RECORD_ROUTE = {
    **REGION_RECORD_FULL,
    "ocr_region": "route",
    "region_type": "route",
    "ocr_text": "BQN SJU",
    "ocr_char_count": 7,
}

REGION_RECORD_LOW_TEXT = {
    **REGION_RECORD_FULL,
    "image_path": "data/img_002.png",
    "ocr_text": "x",
    "ocr_char_count": 1,
}

REGION_RECORD_FAILED = {
    **REGION_RECORD_FULL,
    "image_path": "data/img_003.png",
    "ocr_status": "failed",
    "ocr_text": "",
    "ocr_char_count": 0,
    "error": "FileNotFoundError",
}


# ---------------------------------------------------------------------------
# Region parser tests
# ---------------------------------------------------------------------------

class TestRegionParser:
    def test_reads_jsonl_and_emits_candidate_fields(self, tmp_path):
        jsonl = tmp_path / "region.jsonl"
        _write_jsonl(jsonl, [REGION_RECORD_FULL])
        out_csv = tmp_path / "out.csv"

        summary = region_parse_jsonl(jsonl, out_csv)

        assert out_csv.exists()
        rows = _read_csv(out_csv)
        assert len(rows) == 1
        row = rows[0]
        assert row["image_path"] == "data/img_001.png"
        assert row["callsign_or_label"] == "N1234A"
        assert row["barometric_altitude_ft"] == "8500"
        assert row["ground_speed_mph"] == "185"
        assert row["origin_code"] == "BQN"
        assert row["destination_code"] == "SJU"
        assert row["aircraft_type"] != ""
        assert summary["records"] == 1

    def test_no_confirmed_labels(self, tmp_path):
        jsonl = tmp_path / "region.jsonl"
        _write_jsonl(jsonl, [REGION_RECORD_FULL, REGION_RECORD_LOW_TEXT, REGION_RECORD_FAILED])
        out_csv = tmp_path / "out.csv"

        region_parse_jsonl(jsonl, out_csv)
        rows = _read_csv(out_csv)

        disallowed = {"confirmed", "confirmed_anomaly", "confirmed_aircraft_event", "confirmed_infrastructure"}
        for row in rows:
            assert row["review_status"] not in disallowed, f"Disallowed label: {row['review_status']}"

    def test_callsign_region_extracts_callsign(self, tmp_path):
        row = parse_region_record(REGION_RECORD_CALLSIGN)
        assert row["callsign_or_label"] == "N1234A"

    def test_altitude_region_extracts_altitude(self, tmp_path):
        row = parse_region_record(REGION_RECORD_ALTITUDE)
        assert row["barometric_altitude_ft"] == "8500"
        assert row["callsign_or_label"] == ""

    def test_speed_region_extracts_speed(self, tmp_path):
        row = parse_region_record(REGION_RECORD_SPEED)
        assert row["ground_speed_mph"] == "185"

    def test_route_region_extracts_codes(self, tmp_path):
        row = parse_region_record(REGION_RECORD_ROUTE)
        assert row["origin_code"] == "BQN"
        assert row["destination_code"] == "SJU"

    def test_low_text_gets_low_text_review_status(self, tmp_path):
        row = parse_region_record(REGION_RECORD_LOW_TEXT)
        assert row["review_status"] == "region_low_text_review"

    def test_failed_ocr_gets_failed_status(self, tmp_path):
        row = parse_region_record(REGION_RECORD_FAILED)
        assert row["review_status"] == "region_ocr_failed"

    def test_provenance_fields_preserved(self, tmp_path):
        row = parse_region_record(REGION_RECORD_FULL)
        assert row["sidecar_path"] == "data/IMG_001.json"
        assert row["match_band"] == "strong"
        assert row["resolved_status"] == "matched_primary"
        assert row["region_type"] == "panel"
        assert "parser_version" in row


# ---------------------------------------------------------------------------
# Fusion tests
# ---------------------------------------------------------------------------

class TestFusion:
    def _wi_rows(self, registration="N1234A", aircraft_type="Boeing C-17A Globemaster III"):
        return [{
            "image_path": "data/img_001.png",
            "image_name": "img_001.png",
            "sidecar_path": "data/IMG_001.json",
            "sidecar_title": "IMG_001.PNG",
            "match_band": "strong",
            "resolved_status": "matched_primary",
            "callsign_or_label": "N1234A",
            "registration": registration,
            "aircraft_type": aircraft_type,
            "origin_code": "BQN",
            "destination_code": "SJU",
            "barometric_altitude_ft": "8500",
            "ground_speed_mph": "185",
            "confidence": "0.85",
            "review_status": "parsed_candidate",
        }]

    def _region_rows(self, registration="N1234A"):
        return {
            "data/img_001.png": [{
                "image_path": "data/img_001.png",
                "image_name": "img_001.png",
                "sidecar_path": "data/IMG_001.json",
                "sidecar_title": "IMG_001.PNG",
                "match_band": "strong",
                "resolved_status": "matched_primary",
                "region_type": "panel",
                "callsign_or_label": "N1234A",
                "registration": registration,
                "aircraft_type": "Boeing C-17A Globemaster III",
                "origin_code": "BQN",
                "destination_code": "SJU",
                "barometric_altitude_ft": "8500",
                "ground_speed_mph": "185",
            }]
        }

    def test_preserves_whole_image_source_fields(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows()
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))
        region_rec = dict(REGION_RECORD_FULL)
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        rows = _read_csv(out_csv)
        assert len(rows) == 1
        row = rows[0]
        assert row["callsign_or_label_wi"] == "N1234A"
        assert row["registration_wi"] == "N1234A"

    def test_preserves_region_source_fields(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows()
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))
        region_rec = dict(REGION_RECORD_FULL)
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        rows = _read_csv(out_csv)
        row = rows[0]
        assert "registration_region" in row

    def test_flags_conflicts_instead_of_overwriting(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows()
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))

        # Region text has a different callsign (N9999Z vs N1234A) to force a conflict.
        region_rec = dict(REGION_RECORD_FULL)
        region_rec["ocr_text"] = "N9999Z (SJU) Private owner Sikorsky MH-60T Jayhawk SJU BQN 8500 ft 185 mph"
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        rows = _read_csv(out_csv)
        row = rows[0]

        assert row["review_status"] == "fusion_conflict_review"
        conflict_fields = row["conflict_fields"].split(",")
        # callsign_or_label: whole-image "N1234A" vs region "N9999Z" → conflict
        assert "callsign_or_label" in conflict_fields

        # Both source values must be preserved, not merged
        assert row.get("callsign_or_label_wi") == "N1234A"
        assert row.get("callsign_or_label_region") == "N9999Z"

    def test_no_conflict_yields_fused_candidate(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows(registration="N1234A")
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))
        region_rec = dict(REGION_RECORD_FULL)
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        rows = _read_csv(out_csv)
        assert rows[0]["review_status"] == "fused_candidate"

    def test_conflict_rows_appear_in_review_csv(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows()
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))
        region_rec = dict(REGION_RECORD_FULL)
        # Different callsign in parentheses → callsign conflict after region parse
        region_rec["ocr_text"] = "N9999Z (SJU) Private owner 8500 ft 185 mph BQN"
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        review_rows = _read_csv(review_csv)
        assert len(review_rows) >= 1
        assert all(r["review_status"] == "fusion_conflict_review" for r in review_rows)

    def test_no_confirmed_labels_in_fusion_output(self, tmp_path):
        wi_csv = tmp_path / "wi.csv"
        region_csv = tmp_path / "region.csv"
        out_csv = tmp_path / "fused.csv"
        review_csv = tmp_path / "review.csv"

        wi_rows = self._wi_rows()
        _write_csv(wi_csv, wi_rows, list(wi_rows[0].keys()))
        region_rec = dict(REGION_RECORD_FULL)
        _write_jsonl(tmp_path / "r.jsonl", [region_rec])
        region_parse_jsonl(tmp_path / "r.jsonl", region_csv)

        run_fusion(wi_csv, region_csv, out_csv, review_csv)

        disallowed = {"confirmed", "confirmed_anomaly", "confirmed_aircraft_event", "confirmed_infrastructure"}
        for row in _read_csv(out_csv):
            assert row["review_status"] not in disallowed


# ---------------------------------------------------------------------------
# Batch runner tests
# ---------------------------------------------------------------------------

def _make_batch_plan(tmp_path: Path, images: list, batch_id: str = "fr24_batch_0001") -> Path:
    plan_path = tmp_path / "batch_plan.csv"
    rows = []
    for i, img in enumerate(images, 1):
        rows.append({
            "batch_id": batch_id,
            "batch_seq": str(i),
            "image_path": img,
            "image_name": Path(img).name,
            "sidecar_path": "",
            "sidecar_title": "",
            "match_band": "strong",
            "resolved_status": "matched_primary",
            "review_status": "sidecar_linked",
        })
    _write_csv(plan_path, rows, list(rows[0].keys()))
    return plan_path


class TestBatchRunner:
    def test_processes_only_requested_batch_id(self, tmp_path):
        images_b1 = [str(tmp_path / "img_001.png")]
        images_b2 = [str(tmp_path / "img_002.png")]

        plan_path = tmp_path / "plan.csv"
        rows = []
        for i, img in enumerate(images_b1, 1):
            rows.append({"batch_id": "fr24_batch_0001", "batch_seq": str(i), "image_path": img,
                         "image_name": Path(img).name, "sidecar_path": "", "sidecar_title": "",
                         "match_band": "strong", "resolved_status": "matched_primary", "review_status": "sidecar_linked"})
        for i, img in enumerate(images_b2, 1):
            rows.append({"batch_id": "fr24_batch_0002", "batch_seq": str(i), "image_path": img,
                         "image_name": Path(img).name, "sidecar_path": "", "sidecar_title": "",
                         "match_band": "strong", "resolved_status": "matched_primary", "review_status": "sidecar_linked"})
        _write_csv(plan_path, rows, list(rows[0].keys()))

        run_batch(plan_path, "fr24_batch_0001", "whole-image", tmp_path)

        ledger = _read_csv(tmp_path / "fr24_batch_run_ledger.csv")
        batch_ids = {r["batch_id"] for r in ledger}
        assert batch_ids == {"fr24_batch_0001"}

    def test_skips_completed_images_on_rerun(self, tmp_path):
        img = str(tmp_path / "img_001.png")
        plan = _make_batch_plan(tmp_path, [img])

        # Pre-seed the ledger with status=complete rather than running the batch
        # twice, because Pillow/pytesseract may not be installed in CI — real OCR
        # would fail and record status=failed, which would not be skipped on rerun.
        from fr24.batch_run import LEDGER_FIELDS, _append_ledger
        import uuid
        ledger_path = tmp_path / "fr24_batch_run_ledger.csv"
        _append_ledger(ledger_path, {
            "ledger_id": str(uuid.uuid4()),
            "batch_id": "fr24_batch_0001",
            "mode": "whole-image",
            "batch_seq": "1",
            "image_path": img,
            "image_name": "img_001.png",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:00:01+00:00",
            "status": "complete",
            "ocr_char_count": "250",
            "regions_ocr_count": "1",
            "error": "",
        })

        run_batch(plan, "fr24_batch_0001", "whole-image", tmp_path)

        ledger = _read_csv(ledger_path)
        matching = [r for r in ledger
                    if r["image_path"] == img and r["batch_id"] == "fr24_batch_0001"
                    and r["mode"] == "whole-image"]
        assert len(matching) == 1, "Pre-seeded complete image must be skipped"
        assert matching[0]["status"] == "complete"

    def test_writes_status_json(self, tmp_path):
        img = str(tmp_path / "img_001.png")
        plan = _make_batch_plan(tmp_path, [img])

        run_batch(plan, "fr24_batch_0001", "whole-image", tmp_path)

        status_path = tmp_path / "batches" / "fr24_batch_0001_status.json"
        assert status_path.exists()
        status = json.loads(status_path.read_text())
        assert status["batch_id"] == "fr24_batch_0001"
        assert status["mode"] == "whole-image"
        assert "total" in status
        assert "complete" in status
        assert "failed" in status

    def test_writes_error_queue_without_crashing(self, tmp_path):
        missing_images = [
            str(tmp_path / "does_not_exist_001.png"),
            str(tmp_path / "does_not_exist_002.png"),
        ]
        plan = _make_batch_plan(tmp_path, missing_images)

        result = run_batch(plan, "fr24_batch_0001", "whole-image", tmp_path)

        assert result is not None
        error_queue = tmp_path / "fr24_batch_error_queue.csv"
        assert error_queue.exists()
        errors = _read_csv(error_queue)
        assert len(errors) >= 1

    def test_no_output_uses_confirmed_labels(self, tmp_path):
        img = str(tmp_path / "img_001.png")
        plan = _make_batch_plan(tmp_path, [img])

        run_batch(plan, "fr24_batch_0001", "whole-image", tmp_path)

        ledger_path = tmp_path / "fr24_batch_run_ledger.csv"
        if ledger_path.exists():
            disallowed = {"confirmed", "confirmed_anomaly", "confirmed_aircraft_event", "confirmed_infrastructure"}
            for row in _read_csv(ledger_path):
                assert row.get("status") not in disallowed

    def test_limit_restricts_images_processed(self, tmp_path):
        images = [str(tmp_path / f"img_{i:03d}.png") for i in range(5)]
        plan = _make_batch_plan(tmp_path, images)

        result = run_batch(plan, "fr24_batch_0001", "whole-image", tmp_path, limit=2)

        assert result["total"] == 2

    def test_region_mode_creates_region_ocr_jsonl(self, tmp_path):
        img = str(tmp_path / "img_001.png")
        plan = _make_batch_plan(tmp_path, [img])

        run_batch(plan, "fr24_batch_0001", "region", tmp_path)

        region_jsonl = tmp_path / "batches" / "fr24_batch_0001_region_ocr.jsonl"
        assert region_jsonl.exists(), "region mode must write _region_ocr.jsonl"

    def test_batch_status_handles_missing_ledger(self, tmp_path):
        missing = tmp_path / "no_ledger.csv"
        rows = read_ledger(missing)
        assert rows == []
        summary = summarize(rows)
        assert summary["overall"]["total_rows"] == 0
        assert summary["overall"]["complete"] == 0


# ---------------------------------------------------------------------------
# Batch status tests
# ---------------------------------------------------------------------------

class TestBatchStatus:
    def test_summarizes_by_batch_id_and_mode(self, tmp_path):
        ledger_path = tmp_path / "ledger.csv"
        rows = [
            {"ledger_id": "a", "batch_id": "fr24_batch_0001", "mode": "whole-image",
             "batch_seq": "1", "image_path": "img1.png", "image_name": "img1.png",
             "started_at": "", "completed_at": "", "status": "complete",
             "ocr_char_count": "100", "regions_ocr_count": "1", "error": ""},
            {"ledger_id": "b", "batch_id": "fr24_batch_0001", "mode": "whole-image",
             "batch_seq": "2", "image_path": "img2.png", "image_name": "img2.png",
             "started_at": "", "completed_at": "", "status": "failed",
             "ocr_char_count": "0", "regions_ocr_count": "0", "error": "err"},
        ]
        from fr24.batch_run import LEDGER_FIELDS
        _write_csv(ledger_path, rows, LEDGER_FIELDS)

        loaded = read_ledger(ledger_path)
        summary = summarize(loaded)

        assert summary["batches"]["fr24_batch_0001"]["whole-image"]["complete"] == 1
        assert summary["batches"]["fr24_batch_0001"]["whole-image"]["failed"] == 1
        assert summary["overall"]["complete"] == 1
        assert summary["overall"]["failed"] == 1
