from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sqlite3

from fr24 import rlsm_intelligence_audit
from skywatcher.fr24 import screenshot_certification as certification_module
from skywatcher.fr24.screenshot_certification import ScreenshotCertification

REPO = Path(__file__).resolve().parents[1]
RLSM_SCHEMA = REPO / "data" / "rlsm" / "schema.sql"
GOLD_SCHEMA = REPO / "schemas" / "rlsm" / "gold_sample.v1.schema.json"


def _service(tmp_path: Path, count: int = 300) -> ScreenshotCertification:
    root = tmp_path / "repo"
    (root / "data" / "rlsm").mkdir(parents=True)
    (root / "data" / "FR24_baseline").mkdir(parents=True)
    (root / "schemas" / "rlsm").mkdir(parents=True)
    (root / "schemas" / "rlsm" / "gold_sample.v1.schema.json").write_bytes(
        GOLD_SCHEMA.read_bytes()
    )
    db_path = root / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(RLSM_SCHEMA.read_text(encoding="utf-8"))
    for index in range(1, count + 1):
        sha = f"{index:064x}"[-64:]
        conn.execute(
            """INSERT INTO screenshots
               (sha256,filename,rel_path,month_bucket,filename_ts,ext,size_bytes,
                width,height,phash,ingest_status,ocr_status,source_availability,ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sha,
                f"frame-{index:04d}.png",
                f"data/FR24_baseline/frame-{index:04d}.png",
                f"2026-{((index - 1) % 12) + 1:02d}",
                "2026-01-01T00:00:00-04:00",
                ".png",
                1,
                100 if index % 2 else 200,
                200 if index % 2 else 100,
                f"{index % 16:016x}",
                "ok",
                "ok",
                "present",
                "2026-01-01T00:00:00Z",
            ),
        )
    conn.commit()
    conn.close()
    return ScreenshotCertification(root)


def _template_rows(service: ScreenshotCertification) -> list[dict]:
    result = service.generate_gold_template()
    payload = base64.b64decode(result["data_base64"])
    return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line]


def _review(rows: list[dict]) -> bytes:
    reviewed = []
    for row in rows:
        item = dict(row)
        item["annotator"] = "annotator-a"
        item["reviewed_by"] = "reviewer-b"
        item["review_state"] = "reviewed"
        item["notes"] = "independently reviewed fixture"
        reviewed.append(item)
    return "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
        for item in reviewed
    ).encode("utf-8")


def test_template_is_deterministic_unique_and_unreviewed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.generate_gold_template()
    second = service.generate_gold_template()

    assert first["sha256"] == second["sha256"]
    assert first["selection_manifest"] == second["selection_manifest"]
    rows = _template_rows(service)
    assert len(rows) == 300
    assert len({row["screenshot_id"] for row in rows}) == 300
    assert all(row["review_state"] == "unreviewed" for row in rows)
    assert first["selection_manifest"]["selection_method"] == (
        "deterministic_stratum_round_robin_v1"
    )

    validation = service.validate_gold(
        "gold_sample_300.jsonl",
        base64.b64decode(first["data_base64"]),
    )
    assert validation["exact_denominator"] is True
    assert validation["unreviewed_records"] == 300
    assert validation["valid_for_certification_attempt"] is False


def test_reviewed_template_closes_preflight_contract(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = _review(_template_rows(service))
    validation = service.validate_gold("gold_sample_300.jsonl", payload)

    assert validation["records"] == 300
    assert validation["schema_errors"] == []
    assert validation["duplicate_raw_identities"] == 0
    assert validation["unreviewed_records"] == 0
    assert validation["non_independent_review_records"] == 0
    assert validation["labels_not_explicit_records"] == 0
    assert validation["valid_for_certification_attempt"] is True


def test_gold_evaluator_rejects_duplicate_resolved_frames(tmp_path: Path) -> None:
    service = _service(tmp_path)
    rows = _template_rows(service)
    rows[-1]["screenshot_id"] = rows[0]["screenshot_id"]
    rows[-1]["screenshot_sha256"] = rows[0]["screenshot_sha256"]
    rows[-1]["filename"] = rows[0]["filename"]
    payload = _review(rows)
    gold = tmp_path / "duplicate.jsonl"
    gold.write_bytes(payload)

    conn = sqlite3.connect(service.db_path)
    metrics, errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=300,
        require_independent_review=True,
    )
    conn.close()

    assert metrics["status"] == "incomplete"
    assert metrics["duplicate_resolved_records"] == 1
    assert metrics["unique_resolved_records"] == 299
    assert any(error["kind"] == "gold_duplicate_screenshot" for error in errors)


def test_gold_evaluator_requires_distinct_review_and_explicit_labels(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, count=1)
    row = _template_rows(_service(tmp_path / "larger"))[0]
    row["screenshot_id"] = 1
    row["screenshot_sha256"] = f"{1:064x}"
    row["filename"] = "frame-0001.png"
    row.pop("labels", None)
    row["annotator"] = "same-person"
    row["reviewed_by"] = "same-person"
    row["review_state"] = "reviewed"
    gold = tmp_path / "one.jsonl"
    gold.write_text(json.dumps(row) + "\n", encoding="utf-8")

    conn = sqlite3.connect(service.db_path)
    metrics, errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=1,
        require_independent_review=True,
    )
    conn.close()

    assert metrics["status"] == "incomplete"
    assert metrics["independent_review_violations"] == 1
    assert metrics["unannotated_label_rows"] == 1
    kinds = {error["kind"] for error in errors}
    assert "gold_independent_review_missing" in kinds
    assert "gold_labels_not_explicitly_annotated" in kinds


def test_gold_source_byte_identity_passes_then_fails_on_mutation(tmp_path: Path) -> None:
    service = _service(tmp_path, count=1)
    source = service.corpus_root / "frame-0001.png"
    source.write_bytes(b"gold-frame")
    expected_sha = hashlib.sha256(source.read_bytes()).hexdigest()

    conn = sqlite3.connect(service.db_path)
    conn.execute(
        """UPDATE screenshots
           SET sha256=?, rel_path=?, size_bytes=?
           WHERE screenshot_id=1""",
        (
            expected_sha,
            "data/FR24_baseline/frame-0001.png",
            source.stat().st_size,
        ),
    )
    conn.commit()
    conn.close()

    gold_row = {
        "screenshot_id": 1,
        "screenshot_sha256": expected_sha,
        "filename": "frame-0001.png",
        "labels": [],
        "annotator": "annotator-a",
        "reviewed_by": "reviewer-b",
        "review_state": "reviewed",
    }
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps(gold_row) + "\n", encoding="utf-8")

    conn = sqlite3.connect(service.db_path)
    passed, pass_errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=1,
        require_independent_review=True,
        corpus_root=service.corpus_root,
    )
    conn.close()

    assert passed["status"] == "ready"
    assert passed["source_bytes_verified"] == 1
    assert passed["source_byte_failures"] == 0
    assert not any(error["kind"] == "gold_source_sha256_mismatch" for error in pass_errors)

    source.write_bytes(b"mutated-frame")
    conn = sqlite3.connect(service.db_path)
    failed, fail_errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=1,
        require_independent_review=True,
        corpus_root=service.corpus_root,
    )
    conn.close()

    assert failed["status"] == "incomplete"
    assert failed["source_bytes_verified"] == 0
    assert failed["source_byte_failures"] == 1
    assert any(error["kind"] == "gold_source_sha256_mismatch" for error in fail_errors)


def test_audit_receipt_is_idempotent_and_freezes_input_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    payload = _review(_template_rows(service))

    def fake_run(*, db_path, corpus_root, gold_path, outputs_dir, sample_limit):
        outputs_dir.mkdir(parents=True, exist_ok=True)
        report_path = outputs_dir / "screenshot_intelligence_audit.json"
        report_path.write_text('{"fixture":true}\n', encoding="utf-8")
        return {
            "certification_status": "PASS",
            "gold_sample": {
                "status": "ready",
                "records": 300,
                "unique_resolved_records": 300,
                "label_metrics": {"recall": 1.0},
                "aircraft_field_accuracy": 1.0,
            },
            "required_gates": ["location_label_recall_gte_0_98"],
            "gates": {
                "location_label_recall_gte_0_98": {
                    "status": "PASS",
                    "evidence": {"recall": 1.0},
                }
            },
            "error_count": 0,
        }

    monkeypatch.setattr(certification_module.audit_v2, "run", fake_run)
    first = service.run_audit("gold_sample_300.jsonl", payload)
    second = service.run_audit("gold_sample_300.jsonl", payload)

    assert first == second
    assert first["certification_status"] == "PASS"
    assert first["audit_certification_status"] == "PASS"
    assert first["inputs"]["inputs_stable_during_audit"] is True
    assert first["inputs"]["rlsm_database_manifest_before"] == (
        first["inputs"]["rlsm_database_manifest_after"]
    )
    assert first["inputs"]["corpus_manifest_before"] == (
        first["inputs"]["corpus_manifest_after"]
    )
    assert first["canonical_mfl_mutation_authorized"] is False
    assert (
        "outputs/screenshot_intelligence_audit.json"
        in first["output_hashes"]
    )
