from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PIL import Image

from fr24 import rlsm_calibration as calibration
from fr24 import rlsm_corpus_ingest as corpus


def _freeze_two_cases(tmp_path: Path) -> tuple[Path, Path, str, list[tuple[int, str, str]]]:
    baseline = tmp_path / "data" / "FR24_baseline"
    archives = tmp_path / "data" / "FR24_archives"
    database = tmp_path / "data" / "rlsm" / "test.sqlite"
    output = tmp_path / "outputs" / "rlsm_corpus"
    baseline.mkdir(parents=True)
    archives.mkdir(parents=True)
    for name, value in (("positive.png", 20), ("negative.png", 200)):
        Image.new("RGB", (20, 20), (value, value, value)).save(baseline / name)
    cert = corpus.run(
        db_path=database,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )
    assert cert["status"] == "PASS"
    conn = sqlite3.connect(database)
    try:
        rows = [
            (int(sid), str(sha), str(path))
            for sid, sha, path in conn.execute(
                "SELECT screenshot_id, sha256, rel_path FROM screenshots ORDER BY filename"
            )
        ]
    finally:
        conn.close()
    return database, baseline, str(cert["corpus_digest"]), rows


def _manifest(digest: str, rows: list[tuple[int, str, str]]) -> dict:
    by_name = {Path(path).name: (sid, sha) for sid, sha, path in rows}
    positive_id, positive_sha = by_name["positive.png"]
    negative_id, negative_sha = by_name["negative.png"]
    return {
        "schema_version": calibration.CALIBRATION_PROTOCOL,
        "corpus_digest": digest,
        "acceptance": {
            "min_cases": 2,
            "min_zone_exact_rate": 1.0,
            "max_mean_char_error_rate": 0.0,
            "max_hard_negative_false_positive_rate": 0.0,
            "required_strata": [
                "FR24_AIRCRAFT_SELECTED|portrait|positive",
                "FR24_MAP_STANDARD|portrait|hard_negative",
            ],
        },
        "cases": [
            {
                "screenshot_id": positive_id,
                "sha256": positive_sha,
                "screenshot_family": "FR24_AIRCRAFT_SELECTED",
                "orientation": "portrait",
                "case_role": "positive",
                "zones": {"aircraft_card": "N407PR"},
            },
            {
                "screenshot_id": negative_id,
                "sha256": negative_sha,
                "screenshot_family": "FR24_MAP_STANDARD",
                "orientation": "portrait",
                "case_role": "hard_negative",
                "zones": {"aircraft_card": "NO AIRCRAFT"},
            },
        ],
    }


def _fake_ocr_case(path: Path):
    if path.name == "positive.png":
        return {"aircraft_card": "N407PR"}, {"aircraft_card": 99.0}
    return {"aircraft_card": "NO AIRCRAFT"}, {"aircraft_card": 99.0}


def test_empirical_calibration_pass_is_bound_to_exact_corpus(
    tmp_path: Path, monkeypatch
) -> None:
    database, _baseline, digest, rows = _freeze_two_cases(tmp_path)
    manifest_path = tmp_path / "calibration.json"
    manifest_path.write_text(json.dumps(_manifest(digest, rows)), encoding="utf-8")

    monkeypatch.setattr(calibration, "_ocr_case", _fake_ocr_case)
    result = calibration.run(
        manifest_path,
        db_path=database,
        repo_root=tmp_path,
        output_dir=tmp_path / "outputs" / "rlsm_calibration",
    )
    assert result["status"] == "PASS"
    assert result["mass_ocr_ready"] is True

    conn = sqlite3.connect(database)
    try:
        row = conn.execute(
            """SELECT status, bound_corpus_digest, evidence_sha256
               FROM pipeline_certifications WHERE gate_name=?""",
            (corpus.OCR_GATE,),
        ).fetchone()
        assert row is not None
        assert row[0] == "PASS"
        assert row[1] == digest
        assert row[2] == result["evidence_sha256"]

        mass = conn.execute(
            """SELECT status, bound_corpus_digest, evidence_sha256
               FROM pipeline_certifications WHERE gate_name=?""",
            (corpus.MASS_OCR_GATE,),
        ).fetchone()
        assert mass == ("PASS", digest, result["evidence_sha256"])

        # A production OCR run can be created only after the composite gate passes.
        conn.execute(
            """INSERT INTO processing_runs(run_kind, started_at, status)
               VALUES ('ocr_parallel', '2026-08-22T00:00:00Z', 'in_progress')"""
        )
    finally:
        conn.close()


def test_corpus_change_invalidates_prior_calibration(tmp_path: Path, monkeypatch) -> None:
    database, baseline, digest, rows = _freeze_two_cases(tmp_path)
    manifest_path = tmp_path / "calibration.json"
    manifest_path.write_text(json.dumps(_manifest(digest, rows)), encoding="utf-8")

    monkeypatch.setattr(calibration, "_ocr_case", _fake_ocr_case)
    first = calibration.run(
        manifest_path,
        db_path=database,
        repo_root=tmp_path,
        output_dir=tmp_path / "outputs" / "rlsm_calibration",
    )
    assert first["mass_ocr_ready"] is True

    Image.new("RGB", (20, 20), (100, 110, 120)).save(baseline / "new_case.png")
    new_cert = corpus.run(
        db_path=database,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[tmp_path / "data" / "FR24_archives"],
        output_dir=tmp_path / "outputs" / "rlsm_corpus",
    )
    assert new_cert["corpus_digest"] != digest
    assert new_cert["gates"]["ocr_calibration_bound_pass"] is False
    assert new_cert["gates"]["mass_ocr_ready"] is False

    conn = sqlite3.connect(database)
    try:
        calibration_row = conn.execute(
            """SELECT status, bound_corpus_digest
               FROM pipeline_certifications WHERE gate_name=?""",
            (corpus.OCR_GATE,),
        ).fetchone()
        assert calibration_row == ("OPEN", new_cert["corpus_digest"])
        mass_row = conn.execute(
            """SELECT status, bound_corpus_digest
               FROM pipeline_certifications WHERE gate_name=?""",
            (corpus.MASS_OCR_GATE,),
        ).fetchone()
        assert mass_row == ("OPEN", new_cert["corpus_digest"])
    finally:
        conn.close()


def test_calibration_manifest_requires_positive_and_hard_negative(tmp_path: Path) -> None:
    database, _baseline, digest, rows = _freeze_two_cases(tmp_path)
    manifest = _manifest(digest, rows)
    manifest["cases"] = [manifest["cases"][0], dict(manifest["cases"][0])]
    manifest["cases"][1]["screenshot_id"] += 1000
    manifest_path = tmp_path / "bad_calibration.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        calibration.run(
            manifest_path,
            db_path=database,
            repo_root=tmp_path,
            output_dir=tmp_path / "outputs" / "rlsm_calibration",
        )
    except calibration.CalibrationBlocked as exc:
        assert "both positive and hard_negative" in str(exc)
    else:
        raise AssertionError("single-role calibration corpus was accepted")
