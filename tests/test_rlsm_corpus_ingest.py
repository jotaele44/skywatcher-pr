from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from PIL import Image

from fr24 import rlsm_corpus_ingest as corpus


def _image(path: Path, value: int) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 16), (value, value, value)).save(path, format="PNG")
    return path.read_bytes()


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path
    baseline = repo / "data" / "FR24_baseline"
    archives = repo / "data" / "FR24_archives"
    db = repo / "data" / "rlsm" / "test.sqlite"
    output = repo / "outputs" / "rlsm_corpus"
    baseline.mkdir(parents=True)
    archives.mkdir(parents=True)
    return baseline, archives, db, output


def test_exact_duplicate_files_are_preserved_as_manifestations(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    first = baseline / "2026-08" / "a.png"
    payload = _image(first, 40)
    second = baseline / "2026-08" / "b.png"
    second.write_bytes(payload)

    cert = corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )

    assert cert["status"] == "PASS"
    assert cert["counts"]["logical_screenshots"] == 1
    assert cert["counts"]["logical_unique_sha256"] == 1
    assert cert["counts"]["manifestation_states"]["present_new"] == 1
    assert cert["counts"]["manifestation_states"]["duplicate_payload"] == 1
    assert cert["gates"]["ocr_calibration_bound_pass"] is False
    assert cert["gates"]["mass_ocr_ready"] is False

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """SELECT m.rel_path, m.screenshot_id
               FROM source_manifestations m
               WHERE m.source_kind='baseline_file'
               ORDER BY m.rel_path"""
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][1] == rows[1][1]
        assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
    finally:
        conn.close()

    duplicate_report = (output / "04_duplicate_groups.csv").read_text(encoding="utf-8")
    assert "a.png" in duplicate_report
    assert "b.png" in duplicate_report


def test_same_path_changed_bytes_is_hash_mismatch_not_new_identity(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    target = baseline / "2026-08" / "capture.png"
    _image(target, 10)

    first = corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )
    assert first["status"] == "PASS"

    _image(target, 220)
    second = corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )
    assert second["status"] == "FAIL"
    assert second["counts"]["manifestation_states"]["hash_mismatch"] == 1
    assert second["counts"]["unexplained_residue"] >= 1

    conn = sqlite3.connect(db)
    try:
        # A pathname contradiction must not silently mint a second logical payload.
        assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
    finally:
        conn.close()


def _zip(path: Path, member: str, payload: bytes, compression: int) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr(member, payload)


def test_archive_equivalence_uses_member_payloads_not_outer_hash_only(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    payload = _image(baseline / "2026-08" / "a.png", 80)

    _zip(archives / "a.zip", "x/a.png", payload, zipfile.ZIP_STORED)
    _zip(archives / "b.zip", "x/a.png", payload, zipfile.ZIP_DEFLATED)
    _zip(archives / "c.zip", "moved/a.png", payload, zipfile.ZIP_DEFLATED)
    _zip(archives / "d.zip", "different.txt", b"different", zipfile.ZIP_DEFLATED)

    cert = corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )
    assert cert["status"] == "PASS"

    conn = sqlite3.connect(db)
    try:
        classes = {
            (Path(left).name, Path(right).name): classification
            for left, right, classification in conn.execute(
                """SELECT la.locator, ra.locator, e.classification
                   FROM archive_equivalence e
                   JOIN source_archives la ON la.archive_id=e.left_archive_id
                   JOIN source_archives ra ON ra.archive_id=e.right_archive_id
                   ORDER BY la.locator, ra.locator"""
            )
        }
    finally:
        conn.close()

    assert classes[("a.zip", "b.zip")] == "PURE_RECOMPRESSION"
    assert classes[("a.zip", "c.zip")] == "SAME_PAYLOADS_DIFFERENT_PATHS"
    assert classes[("a.zip", "d.zip")] == "DISTINCT_PAYLOADS"


def test_budget_truncation_can_never_certify_pass(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    _image(baseline / "2026-08" / "a.png", 120)

    cert = corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
        budget_sec=1e-12,
    )
    assert cert["status"] == "OPEN_PARTIAL"
    assert cert["gates"]["corpus_freeze_pass"] is False
    assert cert["gates"]["mass_ocr_ready"] is False


def test_filename_timestamp_is_only_candidate_evidence(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    _image(baseline / "2026-08" / "FR24_2026-08-22_14-03-11.png", 55)
    corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """SELECT source_kind, authority
               FROM screenshot_time_observations
               WHERE source_kind='filename'"""
        ).fetchone()
        assert row == ("filename", "CANDIDATE_NOT_IDENTITY")
    finally:
        conn.close()


def test_open_calibration_gate_blocks_production_ocr_insert(tmp_path: Path) -> None:
    baseline, archives, db, output = _paths(tmp_path)
    _image(baseline / "2026-08" / "a.png", 140)
    corpus.run(
        db_path=db,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        screenshot_id = conn.execute(
            "SELECT screenshot_id FROM screenshots"
        ).fetchone()[0]
        run_id = conn.execute(
            """INSERT INTO processing_runs(run_kind, started_at, status)
               VALUES ('ocr', '2026-08-22T00:00:00Z', 'in_progress')"""
        ).lastrowid
        try:
            conn.execute(
                """INSERT INTO ocr_observations
                   (screenshot_id, run_id, zone, raw_text, ocr_status,
                    engine, engine_version, observed_at)
                   VALUES (?, ?, 'aircraft_card', 'N407PR', 'ok',
                           'test', '1', '2026-08-22T00:00:00Z')""",
                (screenshot_id, run_id),
            )
        except sqlite3.IntegrityError as exc:
            assert "RLSM_OCR_CALIBRATION" in str(exc)
        else:
            raise AssertionError(
                "production OCR insert was not blocked by OPEN calibration gate"
            )
    finally:
        conn.close()
