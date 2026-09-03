from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from fr24 import rlsm_ocr, rlsm_ocr_parallel, rlsm_source_availability
from fr24.rlsm_source_availability import (
    AvailabilitySchemaError,
    ReconciliationError,
    RestoreEntry,
    apply_reconciliation,
    backup_database,
    connect_read_only,
    connection_snapshot_sha256,
    has_availability_schema,
    load_restore_manifest,
    migrate_schema,
    plan_digest,
    plan_reconciliation,
    reconcile_apply,
    require_availability_schema,
    sha256_file,
    summarize,
    validate_apply_control_paths,
    validate_report_output_paths,
    write_reports,
)
from scripts import rlsm_inventory

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"


def create_fresh_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def create_legacy_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE screenshots (
            screenshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256 TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            month_bucket TEXT,
            filename_ts TEXT,
            ext TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            width INTEGER,
            height INTEGER,
            phash TEXT,
            dup_group_id INTEGER,
            near_dup_group_id INTEGER,
            ingest_status TEXT NOT NULL,
            ingest_error TEXT,
            ocr_status TEXT NOT NULL DEFAULT 'pending',
            ingested_at TEXT NOT NULL
        );
        CREATE TABLE processing_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_kind TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            n_inputs INTEGER,
            n_processed INTEGER,
            n_failed INTEGER,
            git_sha TEXT,
            notes TEXT
        );
        CREATE TABLE ocr_observations (
            obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id INTEGER NOT NULL,
            run_id INTEGER,
            zone TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            raw_lines_json TEXT,
            ocr_status TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def insert_screenshot(
    conn: sqlite3.Connection,
    rel_path: str,
    data: bytes,
    *,
    availability: str = "present",
    ingest_status: str = "ok",
    ocr_status: str = "pending",
    month: str = "2026-03",
) -> int:
    digest = hashlib.sha256(data).hexdigest()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(screenshots)")}
    if "source_availability" in columns:
        cursor = conn.execute(
            """
            INSERT INTO screenshots
                (sha256, filename, rel_path, month_bucket, ext, size_bytes,
                 ingest_status, ocr_status, ingested_at, source_availability)
            VALUES (?, ?, ?, ?, 'png', ?, ?, ?, '2026-07-30T00:00:00Z', ?)
            """,
            (
                digest,
                Path(rel_path).name,
                rel_path,
                month,
                len(data),
                ingest_status,
                ocr_status,
                availability,
            ),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO screenshots
                (sha256, filename, rel_path, month_bucket, ext, size_bytes,
                 ingest_status, ocr_status, ingested_at)
            VALUES (?, ?, ?, ?, 'png', ?, ?, ?, '2026-07-30T00:00:00Z')
            """,
            (
                digest,
                Path(rel_path).name,
                rel_path,
                month,
                len(data),
                ingest_status,
                ocr_status,
            ),
        )
    conn.commit()
    return int(cursor.lastrowid)


def apply_locked(
    db: Path,
    repo_root: Path,
    *,
    restore_entries: dict[str, RestoreEntry] | None = None,
    verify_sha: bool = False,
    fault_hook=None,
    backup_name: str = "before.sqlite",
):
    stamp = "2026-07-30T00:00:00Z"
    read_conn = connect_read_only(db)
    try:
        plan = plan_reconciliation(
            read_conn,
            repo_root,
            verify_sha=verify_sha,
            restore_entries=restore_entries,
            checked_at=stamp,
        )
        digest = plan_digest(plan)
        snapshot = connection_snapshot_sha256(read_conn)
    finally:
        read_conn.close()
    return reconcile_apply(
        db,
        repo_root,
        backup_path=repo_root / backup_name,
        quarantine_dir=repo_root / "quarantine",
        verify_sha=verify_sha,
        restore_entries=restore_entries,
        checked_at=stamp,
        expected_plan_digest=digest,
        expected_snapshot_sha256=snapshot,
        fault_hook=fault_hook,
    )


def test_fresh_schema_has_columns_and_index(tmp_path: Path):
    conn = create_fresh_db(tmp_path / "fresh.sqlite")
    try:
        assert has_availability_schema(conn)
        require_availability_schema(conn)
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(screenshots)")}
        assert "ix_screenshots_source_availability" in indexes
    finally:
        conn.close()


def test_legacy_migration_is_idempotent(tmp_path: Path):
    conn = create_legacy_db(tmp_path / "legacy.sqlite")
    try:
        with pytest.raises(AvailabilitySchemaError):
            require_availability_schema(conn)
        first = migrate_schema(conn)
        second = migrate_schema(conn)
        conn.commit()
        assert set(first) == {
            "source_availability",
            "availability_checked_at",
            "availability_detail",
            "availability_source",
        }
        assert second == []
        require_availability_schema(conn)
    finally:
        conn.close()


def test_dry_run_plan_does_not_change_database_bytes(tmp_path: Path):
    db = tmp_path / "dry.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/a.png", b"a")
    conn.close()
    before = sha256_file(db)
    ro = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        plan = plan_reconciliation(ro, tmp_path, checked_at="2026-07-30T00:00:00Z")
        assert plan[0].proposed_availability == "missing_on_disk"
    finally:
        ro.close()
    assert sha256_file(db) == before


def test_present_to_missing_and_no_row_deletion(tmp_path: Path):
    db = tmp_path / "missing.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    conn.close()

    _, _, receipt, _ = apply_locked(
        db, tmp_path, backup_name="missing.backup.sqlite"
    )
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT source_availability, ingest_status, ocr_status FROM screenshots"
        ).fetchone()
        assert row == ("missing_on_disk", "ok", "pending")
        assert check.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
        assert receipt["database_updates"] == 1
    finally:
        check.close()


def test_exact_sha_restore_and_idempotent_second_plan(tmp_path: Path):
    db = tmp_path / "restore.sqlite"
    conn = create_fresh_db(db)
    data = b"exact-source"
    rel = "data/FR24_baseline/restore.png"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    apply_locked(
        db,
        tmp_path,
        restore_entries=entries,
        verify_sha=True,
        backup_name="restore.backup.sqlite",
    )
    assert (tmp_path / rel).read_bytes() == data

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT source_availability, ingest_status, ocr_status FROM screenshots"
        ).fetchone()
        assert row == ("restored", "ok", "pending")
        second_plan = plan_reconciliation(
            conn,
            tmp_path,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
        )
        assert not any(item.changes_database for item in second_plan)
    finally:
        conn.close()


def test_mismatch_is_quarantined_and_never_restored(tmp_path: Path):
    db = tmp_path / "mismatch.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected", availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "wrong.png"
    candidate.write_bytes(b"wrong")
    entries = {rel: RestoreEntry(rel, str(candidate), None)}
    _, _, _, receipts = apply_locked(
        db,
        tmp_path,
        restore_entries=entries,
        verify_sha=True,
        backup_name="mismatch.backup.sqlite",
    )
    assert not (tmp_path / rel).exists()
    assert receipts[0]["action"] == "quarantined_candidate_copy"
    assert Path(str(receipts[0]["path"])).read_bytes() == b"wrong"
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "missing_on_disk"
    finally:
        check.close()


def test_inventory_sets_present_and_exports_availability(tmp_path: Path, monkeypatch):
    db = tmp_path / "inventory.sqlite"
    conn = create_fresh_db(db)
    image_path = tmp_path / "data" / "FR24_baseline" / "2026-03" / "sample.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(image_path)
    monkeypatch.setattr(rlsm_inventory, "REPO", tmp_path)
    monkeypatch.setattr(rlsm_inventory, "OUTPUTS", tmp_path / "outputs")
    result = rlsm_inventory._ingest_file(
        conn, image_path, str(image_path.relative_to(tmp_path)), 1
    )
    assert result["ok"]
    row = conn.execute(
        "SELECT source_availability, availability_source, availability_checked_at "
        "FROM screenshots"
    ).fetchone()
    assert row[0:2] == ("present", "inventory")
    assert row[2]
    rlsm_inventory._write_outputs(conn)
    with (tmp_path / "outputs" / "rlsm_ingest_manifest.csv").open() as handle:
        header = next(csv.reader(handle))
    assert {
        "source_availability",
        "availability_checked_at",
        "availability_detail",
        "availability_source",
    } <= set(header)
    conn.close()


def seed_ocr_selection_db(path: Path) -> sqlite3.Connection:
    conn = create_fresh_db(path)
    rows = [
        ("present.png", "present", "pending", "2026-03"),
        ("restored.png", "restored", "pending", "2026-03"),
        ("missing.png", "missing_on_disk", "pending", "2026-03"),
        ("present_failed.png", "present", "failed", "2026-04"),
        ("archived.png", "archived", "failed", "2026-04"),
    ]
    for name, availability, ocr_status, month in rows:
        insert_screenshot(
            conn,
            f"data/FR24_baseline/{name}",
            name.encode(),
            availability=availability,
            ocr_status=ocr_status,
            month=month,
        )
    return conn


def test_serial_selection_excludes_unavailable(tmp_path: Path):
    conn = seed_ocr_selection_db(tmp_path / "serial.sqlite")
    sql, params = rlsm_ocr._build_target_query(filter_month="2026-03")
    names = [Path(row[1]).name for row in conn.execute(sql, params).fetchall()]
    assert names == ["present.png", "restored.png"]
    conn.close()


@pytest.mark.parametrize(
    ("retry_failed", "month", "expected"),
    [
        (False, None, {"present.png", "restored.png"}),
        (True, None, {"present.png", "restored.png", "present_failed.png"}),
        (False, "2026-03", {"present.png", "restored.png"}),
    ],
)
def test_parallel_selection_modes(
    tmp_path: Path,
    retry_failed: bool,
    month: str | None,
    expected: set[str],
):
    conn = seed_ocr_selection_db(tmp_path / f"parallel-{retry_failed}-{month}.sqlite")
    sql, params = rlsm_ocr_parallel._build_target_query(
        retry_failed=retry_failed,
        reocr_boxes=False,
        filter_month=month,
    )
    names = {Path(row[1]).name for row in conn.execute(sql, params).fetchall()}
    assert names == expected
    conn.close()


def test_parallel_reocr_boxes_excludes_unavailable(tmp_path: Path):
    conn = seed_ocr_selection_db(tmp_path / "reocr.sqlite")
    ids = {
        Path(rel).name: sid
        for sid, rel in conn.execute("SELECT screenshot_id, rel_path FROM screenshots")
    }
    for name in ("present.png", "restored.png", "missing.png"):
        conn.execute(
            """
            INSERT INTO ocr_observations
                (screenshot_id, zone, raw_text, raw_lines_json,
                 ocr_status, observed_at)
            VALUES (?, 'label_layer', 'x', '[]', 'ok',
                    '2026-07-30T00:00:00Z')
            """,
            (ids[name],),
        )
    conn.commit()
    sql, params = rlsm_ocr_parallel._build_target_query(
        retry_failed=False,
        reocr_boxes=True,
        filter_month=None,
    )
    names = {Path(row[1]).name for row in conn.execute(sql, params).fetchall()}
    assert names == {"present.png", "restored.png"}
    conn.close()


def test_serial_midrun_disappearance_preserves_pending_and_observations(
    tmp_path: Path, monkeypatch
):
    db = tmp_path / "serial-missing.sqlite"
    conn = create_fresh_db(db)
    sid = insert_screenshot(conn, "data/FR24_baseline/gone.png", b"gone")
    before_obs = conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0]
    monkeypatch.setattr(rlsm_ocr, "REPO", tmp_path)
    result = rlsm_ocr.process_screenshot(
        conn, sid, "data/FR24_baseline/gone.png", 1
    )
    row = conn.execute(
        "SELECT source_availability, availability_detail, ocr_status "
        "FROM screenshots WHERE screenshot_id=?",
        (sid,),
    ).fetchone()
    after_obs = conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0]
    assert result["reason"] == "missing_source"
    assert row == ("missing_on_disk", "missing_during_ocr", "pending")
    assert after_obs == before_obs
    conn.close()


def test_parallel_midrun_disappearance_preserves_pending(tmp_path: Path, monkeypatch):
    db = tmp_path / "parallel-missing.sqlite"
    conn = create_fresh_db(db)
    sid = insert_screenshot(conn, "data/FR24_baseline/gone.png", b"gone")
    conn.close()
    monkeypatch.setattr(rlsm_ocr_parallel, "REPO", tmp_path)
    rlsm_ocr_parallel._worker_init(str(db))
    result = rlsm_ocr_parallel._process_one(
        (sid, "data/FR24_baseline/gone.png", 1)
    )
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT source_availability, availability_detail, ocr_status "
            "FROM screenshots WHERE screenshot_id=?",
            (sid,),
        ).fetchone()
    finally:
        check.close()
    assert result["status"] == "missing_source"
    assert row == ("missing_on_disk", "missing_during_ocr", "pending")


def test_report_bytes_are_deterministic(tmp_path: Path):
    db = tmp_path / "reports.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"x")
    plan = plan_reconciliation(conn, tmp_path, checked_at="2026-07-30T00:00:00Z")
    conn.close()
    summary = summarize(plan, mode="dry-run", migration_required=False)
    first = write_reports(tmp_path / "one", plan, summary)
    second = write_reports(tmp_path / "two", plan, summary)
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()

# ---- atomicity, backup binding, and provenance ------------------------------


def test_preplanned_apply_api_is_disabled(tmp_path: Path):
    with pytest.raises(ReconciliationError, match="preplanned apply is disabled"):
        apply_reconciliation(tmp_path / "x.sqlite", [], quarantine_dir=tmp_path)


def test_apply_without_backup_is_blocked(tmp_path: Path):
    db = tmp_path / "no-backup.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"x")
    conn.close()
    with pytest.raises(ReconciliationError, match="requires a verified backup"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=None,
            quarantine_dir=tmp_path / "q",
        )


def test_stale_database_snapshot_is_blocked(tmp_path: Path):
    db = tmp_path / "stale.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"x")
    conn.close()
    ro = connect_read_only(db)
    try:
        plan = plan_reconciliation(ro, tmp_path, checked_at="2026-07-30T00:00:00Z")
        digest = plan_digest(plan)
        snapshot = connection_snapshot_sha256(ro)
    finally:
        ro.close()
    writer = sqlite3.connect(db)
    writer.execute(
        "UPDATE screenshots SET ingest_error='changed-after-plan' WHERE screenshot_id=1"
    )
    writer.commit()
    writer.close()
    with pytest.raises(ReconciliationError, match="database snapshot changed"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "stale.backup.sqlite",
            quarantine_dir=tmp_path / "q",
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
        )
    assert not (tmp_path / "stale.backup.sqlite").exists()


def test_unknown_manifest_path_is_blocked(tmp_path: Path):
    db = tmp_path / "unknown.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/known.png", b"known")
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"unknown")
    with pytest.raises(ReconciliationError, match="unknown screenshots rel_path"):
        plan_reconciliation(
            conn,
            tmp_path,
            restore_entries={
                "data/FR24_baseline/typo.png": RestoreEntry(
                    "data/FR24_baseline/typo.png", str(candidate)
                )
            },
        )
    conn.close()


def test_load_manifest_rejects_unsafe_and_invalid_sha(tmp_path: Path):
    unsafe = tmp_path / "unsafe.csv"
    unsafe.write_text("rel_path,source_path,sha256\n../x.png,/tmp/x,\n")
    with pytest.raises(ReconciliationError, match="unsafe relative path"):
        load_restore_manifest(unsafe)
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("rel_path,source_path,sha256\na.png,/tmp/x,xyz\n")
    with pytest.raises(ReconciliationError, match="invalid restore manifest SHA"):
        load_restore_manifest(invalid)


def test_candidate_changed_after_plan_is_blocked(tmp_path: Path):
    db = tmp_path / "candidate-change.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restore.png"
    expected = b"expected"
    insert_screenshot(conn, rel, expected, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(expected)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    ro = connect_read_only(db)
    try:
        plan = plan_reconciliation(
            ro,
            tmp_path,
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
        )
        digest = plan_digest(plan)
        snapshot = connection_snapshot_sha256(ro)
    finally:
        ro.close()
    candidate.write_bytes(b"changed")
    with pytest.raises(ReconciliationError, match="plan became stale"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "candidate-change.backup.sqlite",
            quarantine_dir=tmp_path / "q",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
        )
    assert not (tmp_path / rel).exists()


def test_existing_mismatch_changed_after_plan_is_blocked(tmp_path: Path):
    db = tmp_path / "existing-change.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    expected_path = tmp_path / rel
    expected_path.parent.mkdir(parents=True)
    expected_path.write_bytes(b"wrong-one")
    ro = connect_read_only(db)
    try:
        plan = plan_reconciliation(
            ro,
            tmp_path,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
        )
        digest = plan_digest(plan)
        snapshot = connection_snapshot_sha256(ro)
    finally:
        ro.close()
    expected_path.write_bytes(b"wrong-two")
    with pytest.raises(ReconciliationError, match="plan became stale"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "existing-change.backup.sqlite",
            quarantine_dir=tmp_path / "q",
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
        )


def test_backup_verifies_every_user_table(tmp_path: Path):
    db = tmp_path / "tables.sqlite"
    conn = create_fresh_db(db)
    conn.execute("CREATE TABLE extra_evidence (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO extra_evidence(value) VALUES ('preserved')")
    conn.commit()
    conn.close()
    receipt = backup_database(db, tmp_path / "tables.backup.sqlite")
    assert "screenshots" in receipt["tables"]
    assert "processing_runs" in receipt["tables"]
    assert receipt["tables"]["extra_evidence"]["rows"] == 1
    backup = sqlite3.connect(tmp_path / "tables.backup.sqlite")
    try:
        assert backup.execute("SELECT value FROM extra_evidence").fetchone()[0] == "preserved"
    finally:
        backup.close()


def test_failed_backup_verification_removes_destination(tmp_path: Path):
    db = tmp_path / "bad-backup.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"x")
    conn.close()
    backup = tmp_path / "bad-backup.before.sqlite"

    def corrupt(stage, context):
        if stage == "after_backup_install_before_verify":
            Path(str(context["backup_path"])).write_bytes(b"not sqlite")

    ro = connect_read_only(db)
    try:
        plan = plan_reconciliation(ro, tmp_path, checked_at="2026-07-30T00:00:00Z")
        digest = plan_digest(plan)
        snapshot = connection_snapshot_sha256(ro)
    finally:
        ro.close()
    with pytest.raises(ReconciliationError, match="atomic reconciliation failed"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=backup,
            quarantine_dir=tmp_path / "q",
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            fault_hook=corrupt,
        )
    assert not backup.exists()


def test_forced_database_failure_compensates_restored_file(tmp_path: Path):
    db = tmp_path / "compensate.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restored.png"
    data = b"exact"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}

    def fail_after_files(stage, context):
        del context
        if stage == "after_file_actions":
            raise RuntimeError("forced database failure")

    with pytest.raises(ReconciliationError, match="forced database failure"):
        apply_locked(
            db,
            tmp_path,
            restore_entries=entries,
            verify_sha=True,
            fault_hook=fail_after_files,
            backup_name="compensate.before.sqlite",
        )
    assert not (tmp_path / rel).exists()
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT source_availability, ocr_status FROM screenshots"
        ).fetchone()
        assert row == ("missing_on_disk", "pending")
        assert check.execute(
            "SELECT COUNT(*) FROM processing_runs WHERE run_kind='source_reconcile'"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_destination_race_never_overwrites(tmp_path: Path):
    db = tmp_path / "race.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/race.png"
    data = b"exact"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    raced = b"raced-destination"

    def create_race(stage, context):
        if stage == "before_restore_install":
            path = Path(str(context["expected_path"]))
            path.write_bytes(raced)

    with pytest.raises(ReconciliationError, match="no overwrite performed"):
        apply_locked(
            db,
            tmp_path,
            restore_entries=entries,
            verify_sha=True,
            fault_hook=create_race,
            backup_name="race.before.sqlite",
        )
    assert (tmp_path / rel).read_bytes() == raced


def test_existing_mismatch_is_excluded_from_available_disk_invariant(tmp_path: Path):
    db = tmp_path / "coverage-mismatch.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"wrong")
    apply_locked(
        db,
        tmp_path,
        verify_sha=True,
        backup_name="coverage-mismatch.before.sqlite",
    )
    check = sqlite3.connect(db)
    try:
        unavailable = {
            (tmp_path / row[0]).resolve()
            for row in check.execute(
                "SELECT rel_path FROM screenshots "
                "WHERE source_availability NOT IN ('present','restored')"
            )
        }
        available_rows = check.execute(
            "SELECT COUNT(*) FROM screenshots "
            "WHERE source_availability IN ('present','restored')"
        ).fetchone()[0]
    finally:
        check.close()
    files = [path]
    eligible_disk = sum(item.resolve() not in unavailable for item in files)
    assert eligible_disk == available_rows == 0


# ---- semantic-review regressions v0.21 -------------------------------------


def test_second_restore_failure_compensates_first_restore(tmp_path: Path):
    db = tmp_path / "multi-action.sqlite"
    conn = create_fresh_db(db)
    first_rel = "data/FR24_baseline/first.png"
    second_rel = "data/FR24_baseline/second.png"
    first_data = b"first"
    second_data = b"second"
    insert_screenshot(conn, first_rel, first_data, availability="missing_on_disk")
    insert_screenshot(conn, second_rel, second_data, availability="missing_on_disk")
    conn.close()
    first_candidate = tmp_path / "first-candidate.png"
    second_candidate = tmp_path / "second-candidate.png"
    first_candidate.write_bytes(first_data)
    second_candidate.write_bytes(second_data)
    entries = {
        first_rel: RestoreEntry(
            first_rel, str(first_candidate), sha256_file(first_candidate)
        ),
        second_rel: RestoreEntry(
            second_rel, str(second_candidate), sha256_file(second_candidate)
        ),
    }
    calls = 0

    def fail_second_restore(stage, context):
        nonlocal calls
        del context
        if stage == "before_restore_install":
            calls += 1
            if calls == 2:
                raise RuntimeError("second restore failed")

    with pytest.raises(ReconciliationError, match="second restore failed"):
        apply_locked(
            db,
            tmp_path,
            restore_entries=entries,
            verify_sha=True,
            fault_hook=fail_second_restore,
            backup_name="multi-action.before.sqlite",
        )
    assert not (tmp_path / first_rel).exists()
    assert not (tmp_path / second_rel).exists()


def test_manifest_entry_for_existing_source_is_rejected(tmp_path: Path):
    db = tmp_path / "unused-manifest.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/present.png"
    data = b"present"
    insert_screenshot(conn, rel, data, availability="present")
    conn.close()
    expected = tmp_path / rel
    expected.parent.mkdir(parents=True)
    expected.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(tmp_path / "unused-candidate.png"))}
    read = connect_read_only(db)
    try:
        with pytest.raises(ReconciliationError, match="entry is unused"):
            plan_reconciliation(
                read,
                tmp_path,
                verify_sha=True,
                restore_entries=entries,
                checked_at="2026-07-30T00:00:00Z",
            )
    finally:
        read.close()


def test_missing_source_appearing_during_backup_blocks_apply(tmp_path: Path):
    db = tmp_path / "appearing.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/appearing.png"
    data = b"appearing"
    insert_screenshot(conn, rel, data, availability="present")
    conn.close()
    expected = tmp_path / rel

    def appear(stage, context):
        del context
        if stage == "after_backup_install_before_verify":
            expected.parent.mkdir(parents=True, exist_ok=True)
            expected.write_bytes(data)

    with pytest.raises(ReconciliationError, match="appeared after locked planning"):
        apply_locked(
            db,
            tmp_path,
            verify_sha=True,
            fault_hook=appear,
            backup_name="appearing.before.sqlite",
        )
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
    finally:
        check.close()


def test_present_source_disappearing_during_backup_blocks_apply(tmp_path: Path):
    db = tmp_path / "disappearing.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/disappearing.png"
    data = b"disappearing"
    insert_screenshot(conn, rel, data, availability="present")
    conn.close()
    expected = tmp_path / rel
    expected.parent.mkdir(parents=True)
    expected.write_bytes(data)

    def disappear(stage, context):
        del context
        if stage == "after_backup_install_before_verify":
            expected.unlink()

    with pytest.raises(ReconciliationError, match="missing|disappeared after locked planning"):
        apply_locked(
            db,
            tmp_path,
            verify_sha=True,
            fault_hook=disappear,
            backup_name="disappearing.before.sqlite",
        )
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
    finally:
        check.close()


def test_backup_content_change_with_same_counts_is_rejected(
    tmp_path: Path, monkeypatch
):
    db = tmp_path / "content.sqlite"
    conn = create_fresh_db(db)
    conn.execute("CREATE TABLE extra_evidence (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO extra_evidence VALUES (1, 'original')")
    conn.commit()
    conn.close()
    backup = tmp_path / "content.before.sqlite"
    original_writer = rlsm_source_availability._write_connection_snapshot

    def write_altered_snapshot(connection, destination):
        method = original_writer(connection, destination)
        altered = sqlite3.connect(destination)
        try:
            altered.execute(
                "UPDATE extra_evidence SET value='altered' WHERE id=1"
            )
            altered.commit()
        finally:
            altered.close()
        return method

    monkeypatch.setattr(
        rlsm_source_availability,
        "_write_connection_snapshot",
        write_altered_snapshot,
    )
    with pytest.raises(ReconciliationError, match="inventory mismatch"):
        backup_database(db, backup)
    assert not backup.exists()


# ---- control-path namespace isolation v0.25 ---------------------------------


def test_backup_equal_expected_source_is_blocked_without_artifact(tmp_path: Path):
    db = tmp_path / "backup-equal.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    backup = tmp_path / rel
    with pytest.raises(ReconciliationError, match="backup destination overlaps expected source"):
        apply_locked(
            db,
            tmp_path,
            backup_name=rel,
        )
    assert not backup.exists()


def test_backup_ancestor_of_expected_source_is_blocked_without_artifact(
    tmp_path: Path,
):
    db = tmp_path / "backup-ancestor.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    backup = tmp_path / "data" / "FR24_baseline"
    with pytest.raises(ReconciliationError, match="backup destination overlaps expected source"):
        apply_locked(
            db,
            tmp_path,
            backup_name="data/FR24_baseline",
        )
    assert not backup.exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
    finally:
        check.close()


def test_backup_equal_restore_candidate_is_blocked(tmp_path: Path):
    db = tmp_path / "backup-candidate.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected", availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    entries = {rel: RestoreEntry(rel, str(candidate))}
    read = connect_read_only(db)
    try:
        decisions = plan_reconciliation(
            read,
            tmp_path,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
        )
    finally:
        read.close()
    with pytest.raises(ReconciliationError, match="backup destination overlaps restore candidate"):
        validate_apply_control_paths(
            db,
            candidate,
            tmp_path / "quarantine",
            decisions,
        )


def test_quarantine_directory_overlapping_expected_source_is_blocked(
    tmp_path: Path,
):
    db = tmp_path / "quarantine-overlap.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    read = connect_read_only(db)
    try:
        decisions = plan_reconciliation(
            read,
            tmp_path,
            checked_at="2026-07-30T00:00:00Z",
        )
    finally:
        read.close()
    with pytest.raises(ReconciliationError, match="quarantine directory overlaps expected source"):
        validate_apply_control_paths(
            db,
            tmp_path / "backup.sqlite",
            tmp_path / "data" / "FR24_baseline",
            decisions,
        )


def test_backup_database_rejects_sqlite_sidecar_path(tmp_path: Path):
    db = tmp_path / "sidecar.sqlite"
    conn = create_fresh_db(db)
    conn.close()
    with pytest.raises(ReconciliationError, match="SQLite sidecar"):
        backup_database(db, Path(f"{db}-wal"))


def test_report_output_at_expected_source_is_blocked_before_write(tmp_path: Path):
    db = tmp_path / "report-overlap.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()
    output = tmp_path / rel
    with pytest.raises(
        ReconciliationError,
        match="report output directory is at or below expected source",
    ):
        validate_report_output_paths(
            output,
            decisions,
            db_path=db,
        )
    assert not output.exists()


# ---- artifact durability and report namespace v0.28 -------------------------


def test_backup_deleted_before_commit_blocks_database_update(tmp_path: Path):
    db = tmp_path / "backup-deleted.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    conn.close()
    backup = tmp_path / "before.sqlite"

    def fault(stage, _context):
        if stage == "before_database_commit":
            backup.unlink()

    with pytest.raises(ReconciliationError, match="verified backup disappeared"):
        apply_locked(
            db,
            tmp_path,
            backup_name=backup.name,
            fault_hook=fault,
        )

    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
        assert check.execute(
            "SELECT COUNT(*) FROM processing_runs"
        ).fetchone()[0] == 0
    finally:
        check.close()
    assert not backup.exists()


def test_backup_replaced_before_commit_compensates_restore(tmp_path: Path):
    db = tmp_path / "backup-replaced.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restored.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    backup = tmp_path / "before.sqlite"

    def fault(stage, _context):
        if stage == "before_database_commit":
            payload = backup.read_bytes()
            replacement = backup.with_suffix(".replacement")
            replacement.write_bytes(payload)
            replacement.replace(backup)

    with pytest.raises(ReconciliationError, match="verified backup inode changed"):
        apply_locked(
            db,
            tmp_path,
            restore_entries=entries,
            verify_sha=True,
            backup_name=backup.name,
            fault_hook=fault,
        )

    assert not (tmp_path / rel).exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "missing_on_disk"
        assert check.execute(
            "SELECT COUNT(*) FROM processing_runs"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_quarantine_deleted_before_commit_blocks_database_update(tmp_path: Path):
    db = tmp_path / "quarantine-deleted.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    expected = tmp_path / rel
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"wrong")
    quarantine = tmp_path / "quarantine"

    def fault(stage, _context):
        if stage == "before_database_commit":
            for item in quarantine.rglob("*"):
                if item.is_file():
                    item.unlink()

    with pytest.raises(ReconciliationError, match="quarantine copy disappeared"):
        apply_locked(
            db,
            tmp_path,
            verify_sha=True,
            backup_name="before.sqlite",
            fault_hook=fault,
        )

    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
        assert check.execute(
            "SELECT COUNT(*) FROM processing_runs"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_quarantine_replaced_before_commit_blocks_database_update(tmp_path: Path):
    db = tmp_path / "quarantine-replaced.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    expected = tmp_path / rel
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"wrong")
    quarantine = tmp_path / "quarantine"

    def fault(stage, _context):
        if stage == "before_database_commit":
            artifact = next(item for item in quarantine.rglob("*") if item.is_file())
            payload = artifact.read_bytes()
            replacement = artifact.with_suffix(".replacement")
            replacement.write_bytes(payload)
            replacement.replace(artifact)

    with pytest.raises(ReconciliationError, match="quarantine copy inode changed"):
        apply_locked(
            db,
            tmp_path,
            verify_sha=True,
            backup_name="before.sqlite",
            fault_hook=fault,
        )

    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
        assert check.execute(
            "SELECT COUNT(*) FROM processing_runs"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_report_file_ancestor_of_expected_source_is_blocked(tmp_path: Path):
    db = tmp_path / "report-expected-ancestor.sqlite"
    conn = create_fresh_db(db)
    rel = "outputs/source_availability_summary.json/child.png"
    insert_screenshot(conn, rel, b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()
    output = tmp_path / "outputs"
    with pytest.raises(ReconciliationError, match="report namespace overlaps expected source|report file overlaps expected source"):
        validate_report_output_paths(output, decisions, db_path=db)
    assert not output.exists()


def test_report_file_ancestor_of_backup_is_blocked(tmp_path: Path):
    output = tmp_path / "outputs"
    backup = output / "source_availability_transitions.csv" / "before.sqlite"
    with pytest.raises(ReconciliationError, match="report namespace overlaps backup file|report file overlaps backup file"):
        validate_report_output_paths(
            output,
            [],
            backup_path=backup,
        )
    assert not output.exists()


def test_report_file_ancestor_of_quarantine_is_blocked(tmp_path: Path):
    output = tmp_path / "outputs"
    quarantine = output / "source_availability_summary.json" / "quarantine"
    with pytest.raises(
        ReconciliationError,
        match="report namespace overlaps quarantine directory|report file overlaps quarantine directory",
    ):
        validate_report_output_paths(
            output,
            [],
            quarantine_dir=quarantine,
        )
    assert not output.exists()


def test_report_file_colliding_with_restore_manifest_is_blocked(tmp_path: Path):
    output = tmp_path / "outputs"
    manifest = output / "source_availability_summary.json"
    with pytest.raises(ReconciliationError, match="report namespace overlaps restore manifest|report file overlaps restore manifest"):
        validate_report_output_paths(
            output,
            [],
            restore_manifest_path=manifest,
        )
    assert not output.exists()


# ---- external corpus links and terminal fail-closed checks v0.31 ------------


def _symlink_directory(link: Path, target: Path) -> None:
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")


def test_external_corpus_symlink_is_supported(tmp_path: Path):
    repo = tmp_path / "repo"
    external = tmp_path / "external-corpus"
    external.mkdir()
    _symlink_directory(repo / "data" / "FR24_baseline", external)
    data = b"external-source"
    (external / "sample.png").write_bytes(data)

    db = tmp_path / "external.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(
        conn,
        "data/FR24_baseline/sample.png",
        data,
    )
    decisions = plan_reconciliation(
        conn,
        repo,
        verify_sha=True,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()

    assert decisions[0].action == "verified_on_disk"
    assert Path(decisions[0].expected_path) == (
        repo.resolve() / "data" / "FR24_baseline" / "sample.png"
    )


def test_external_corpus_symlink_retarget_during_backup_blocks_apply(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    first = tmp_path / "corpus-a"
    second = tmp_path / "corpus-b"
    first.mkdir()
    second.mkdir()
    link = repo / "data" / "FR24_baseline"
    _symlink_directory(link, first)
    data = b"external-source"
    (first / "sample.png").write_bytes(data)

    db = tmp_path / "retarget.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/sample.png", data)
    conn.close()

    read = connect_read_only(db)
    try:
        decisions = plan_reconciliation(
            read,
            repo,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
        )
        digest = plan_digest(decisions)
        snapshot = connection_snapshot_sha256(read)
    finally:
        read.close()

    def fault(stage, _context):
        if stage == "after_backup_install_before_verify":
            link.unlink()
            link.symlink_to(second, target_is_directory=True)

    backup = tmp_path / "retarget.backup.sqlite"
    with pytest.raises(
        ReconciliationError,
        match="expected source resolution changed|expected source disappeared",
    ):
        reconcile_apply(
            db,
            repo,
            backup_path=backup,
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            fault_hook=fault,
        )
    assert backup.is_file()
    check = sqlite3.connect(db)
    try:
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
    finally:
        check.close()


def test_duplicate_screenshot_rel_path_is_blocked(tmp_path: Path):
    db = tmp_path / "duplicate-rel.sqlite"
    conn = create_fresh_db(db)
    conn.execute("DROP INDEX ux_screenshots_rel_path")
    rel = "data/FR24_baseline/duplicate.png"
    insert_screenshot(conn, rel, b"one")
    insert_screenshot(conn, rel, b"two")
    with pytest.raises(ReconciliationError, match="duplicate rel_path"):
        plan_reconciliation(
            conn,
            tmp_path,
            checked_at="2026-07-30T00:00:00Z",
        )
    conn.close()


def test_screenshot_paths_resolving_to_same_inode_are_blocked(tmp_path: Path):
    repo = tmp_path / "repo"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _symlink_directory(repo / "data" / "FR24_baseline", corpus)
    first = corpus / "one.png"
    second = corpus / "two.png"
    first.write_bytes(b"same")
    try:
        second.hardlink_to(first)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    db = tmp_path / "alias.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/one.png", b"same")
    conn.execute(
        """
        INSERT INTO screenshots
            (sha256, filename, rel_path, ext, size_bytes, ingest_status,
             ocr_status, source_availability, ingested_at)
        VALUES (?, 'two.png', 'data/FR24_baseline/two.png', 'png', 4,
                'ok', 'pending', 'present', '2026-07-30T00:00:00Z')
        """,
        ("f" * 64,),
    )
    conn.commit()
    with pytest.raises(ReconciliationError, match="same physical source inode"):
        plan_reconciliation(
            conn,
            repo,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
        )
    conn.close()


def test_quarantine_destination_must_be_independent_inode(tmp_path: Path):
    db = tmp_path / "quarantine-hardlink.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    expected_path = tmp_path / rel
    expected_path.parent.mkdir(parents=True)
    expected_path.write_bytes(b"wrong")
    insert_screenshot(conn, rel, b"expected")
    conn.close()

    quarantine = tmp_path / "quarantine"
    provisional = sqlite3.connect(db)
    decisions = plan_reconciliation(
        provisional,
        tmp_path,
        verify_sha=True,
        checked_at="2026-07-30T00:00:00Z",
    )
    provisional.close()
    decision = decisions[0]
    destination = (
        quarantine
        / f"{decision.screenshot_id:08d}"
        / f"{expected_path.name}.{str(decision.actual_sha256)[:12]}.quarantine"
    )
    destination.parent.mkdir(parents=True)
    try:
        destination.hardlink_to(expected_path)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    read = connect_read_only(db)
    try:
        decisions = plan_reconciliation(
            read,
            tmp_path,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
        )
        digest = plan_digest(decisions)
        snapshot = connection_snapshot_sha256(read)
    finally:
        read.close()

    with pytest.raises(ReconciliationError, match="not an independent copy"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "backup.sqlite",
            quarantine_dir=quarantine,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
        )


def test_report_output_existing_file_is_blocked(tmp_path: Path):
    db = tmp_path / "report-file.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()

    output = tmp_path / "report-output"
    output.write_text("not a directory", encoding="utf-8")
    with pytest.raises(
        ReconciliationError,
        match="not a directory|non-directory ancestor",
    ):
        validate_report_output_paths(output, decisions, db_path=db)


def test_report_destination_directory_is_blocked(tmp_path: Path):
    db = tmp_path / "report-destination.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()

    output = tmp_path / "reports"
    (output / "source_availability_summary.json").mkdir(parents=True)
    with pytest.raises(
        ReconciliationError,
        match="immutable report destination already exists|not a regular file",
    ):
        validate_report_output_paths(output, decisions, db_path=db)


def test_ocr_open_race_is_accounted_as_missing_source(
    tmp_path: Path,
    monkeypatch,
):
    serial_db = tmp_path / "serial-open-race.sqlite"
    serial_conn = create_fresh_db(serial_db)
    serial_rel = "data/FR24_baseline/serial.png"
    serial_path = tmp_path / serial_rel
    serial_path.parent.mkdir(parents=True)
    serial_path.write_bytes(b"source")
    serial_id = insert_screenshot(serial_conn, serial_rel, b"source")

    def missing_open(_path):
        serial_path.unlink(missing_ok=True)
        raise FileNotFoundError(serial_path)

    monkeypatch.setattr(rlsm_ocr, "REPO", tmp_path)
    monkeypatch.setattr(rlsm_ocr.Image, "open", missing_open)
    result = rlsm_ocr.process_screenshot(
        serial_conn,
        serial_id,
        serial_rel,
        1,
    )
    row = serial_conn.execute(
        "SELECT source_availability, availability_detail, ocr_status "
        "FROM screenshots WHERE screenshot_id=?",
        (serial_id,),
    ).fetchone()
    serial_conn.close()

    assert result["reason"] == "missing_source"
    assert row == ("missing_on_disk", "missing_during_ocr", "pending")


def test_parallel_ocr_open_race_is_accounted_as_missing_source(
    tmp_path: Path,
    monkeypatch,
):
    db = tmp_path / "parallel-open-race.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/parallel.png"
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    screenshot_id = insert_screenshot(conn, rel, b"source")
    conn.close()

    def missing_open(_path):
        source.unlink(missing_ok=True)
        raise FileNotFoundError(source)

    monkeypatch.setattr(rlsm_ocr_parallel, "REPO", tmp_path)
    monkeypatch.setattr(rlsm_ocr_parallel.Image, "open", missing_open)
    rlsm_ocr_parallel._worker_init(str(db))
    result = rlsm_ocr_parallel._process_one((screenshot_id, rel, 1))

    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT source_availability, availability_detail, ocr_status "
            "FROM screenshots WHERE screenshot_id=?",
            (screenshot_id,),
        ).fetchone()
    finally:
        check.close()

    assert result["status"] == "missing_source"
    assert row == ("missing_on_disk", "missing_during_ocr", "pending")

# ---- whole-system final candidate v1.0 --------------------------------------


def _locked_plan(db: Path, repo: Path, *, verify_sha: bool = False, entries=None):
    read = connect_read_only(db)
    try:
        decisions = plan_reconciliation(
            read,
            repo,
            verify_sha=verify_sha,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
        )
        return (
            decisions,
            plan_digest(decisions),
            connection_snapshot_sha256(read),
        )
    finally:
        read.close()


def test_fresh_schema_enforces_unique_rel_path_index(tmp_path: Path):
    conn = create_fresh_db(tmp_path / "fresh-unique.sqlite")
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(screenshots)")}
    assert "ux_screenshots_rel_path" in indexes
    insert_screenshot(conn, "data/FR24_baseline/one.png", b"one")
    with pytest.raises(sqlite3.IntegrityError):
        insert_screenshot(conn, "data/FR24_baseline/one.png", b"two")
    conn.close()


def test_legacy_migration_creates_unique_rel_path_index(tmp_path: Path):
    conn = create_legacy_db(tmp_path / "legacy-unique.sqlite")
    migrate_schema(conn)
    conn.commit()
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(screenshots)")}
    assert "ux_screenshots_rel_path" in indexes
    conn.close()


def test_same_content_external_symlink_retarget_is_blocked(tmp_path: Path):
    repo = tmp_path / "repo"
    first = tmp_path / "corpus-a"
    second = tmp_path / "corpus-b"
    first.mkdir()
    second.mkdir()
    link = repo / "data" / "FR24_baseline"
    _symlink_directory(link, first)
    data = b"same-content"
    (first / "sample.png").write_bytes(data)
    (second / "sample.png").write_bytes(data)
    db = tmp_path / "same-content-retarget.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/sample.png", data)
    conn.close()
    decisions, digest, snapshot = _locked_plan(db, repo, verify_sha=True)

    def retarget(stage, _context):
        if stage == "after_backup_install_before_verify":
            link.unlink()
            link.symlink_to(second, target_is_directory=True)

    with pytest.raises(ReconciliationError, match="resolution changed"):
        reconcile_apply(
            db,
            repo,
            backup_path=tmp_path / "retarget.backup.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            fault_hook=retarget,
        )
    assert decisions[0].resolved_expected_path.endswith("corpus-a/sample.png")


def test_screenshot_leaf_symlink_is_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    corpus = repo / "data" / "FR24_baseline"
    corpus.mkdir(parents=True)
    target = tmp_path / "target.png"
    target.write_bytes(b"data")
    link = corpus / "link.png"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    db = tmp_path / "leaf-link.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/link.png", b"data")
    with pytest.raises(ReconciliationError, match="leaf must not be a symlink"):
        plan_reconciliation(conn, repo, verify_sha=True)
    conn.close()


def test_casefold_rel_path_alias_is_rejected(tmp_path: Path):
    db = tmp_path / "casefold.sqlite"
    conn = create_fresh_db(db)
    conn.execute("DROP INDEX ux_screenshots_rel_path")
    insert_screenshot(conn, "data/FR24_baseline/A.png", b"one")
    conn.execute(
        """
        INSERT INTO screenshots
            (sha256, filename, rel_path, ext, size_bytes, ingest_status,
             ocr_status, source_availability, ingested_at)
        VALUES (?, 'a.png', 'data/FR24_baseline/a.png', 'png', 3,
                'ok', 'pending', 'present', '2026-07-30T00:00:00Z')
        """,
        ("e" * 64,),
    )
    conn.commit()
    with pytest.raises(ReconciliationError, match="case-folding rel_path aliases"):
        plan_reconciliation(conn, tmp_path)
    conn.close()


def test_restore_manifest_candidate_path_reuse_is_rejected(tmp_path: Path):
    db = tmp_path / "candidate-reuse.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/one.png", b"one")
    insert_screenshot(conn, "data/FR24_baseline/two.png", b"two")
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"one")
    entries = {
        "data/FR24_baseline/one.png": RestoreEntry(
            "data/FR24_baseline/one.png", str(candidate)
        ),
        "data/FR24_baseline/two.png": RestoreEntry(
            "data/FR24_baseline/two.png", str(candidate)
        ),
    }
    with pytest.raises(ReconciliationError, match="reuses one candidate path"):
        plan_reconciliation(conn, tmp_path, restore_entries=entries)
    conn.close()


def test_apply_publishes_bound_terminal_receipt_before_commit(tmp_path: Path):
    db = tmp_path / "apply-reports.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    conn.close()
    decisions, digest, snapshot = _locked_plan(db, tmp_path)
    output = tmp_path / "reports"
    result = reconcile_apply(
        db,
        tmp_path,
        backup_path=tmp_path / "before.sqlite",
        quarantine_dir=tmp_path / "quarantine",
        checked_at="2026-07-30T00:00:00Z",
        expected_plan_digest=digest,
        expected_snapshot_sha256=snapshot,
        report_output_dir=output,
    )
    _, backup, apply_receipt, _ = result
    terminal = apply_receipt["terminal_receipt"]
    generation = Path(str(terminal["report_generation_dir"]))
    assert generation.is_dir()
    assert {item.name for item in generation.iterdir()} == {
        "source_availability_transitions.csv",
        "source_availability_summary.json",
        "terminal_apply_receipt.json",
    }
    terminal_file = generation / "terminal_apply_receipt.json"
    terminal_payload = json.loads(terminal_file.read_text())
    assert terminal_payload["state"] == "commit_prepared"
    assert terminal_payload["protocol"] == "rlsm-source-availability-v1.0"
    assert terminal_payload["commit_authority"]["run_id"] == apply_receipt["run_id"]
    assert terminal_payload["backup"]["sha256"] == backup["sha256"]
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT status, notes FROM processing_runs WHERE run_id=?",
            (apply_receipt["run_id"],),
        ).fetchone()
        assert row[0] == "completed"
        notes = json.loads(row[1])
        assert notes["state"] == "committed"
        assert notes["terminal_receipt_file"]["sha256"] == sha256_file(
            terminal_file
        )
    finally:
        check.close()
    assert decisions[0].action == "mark_missing"


def test_report_and_restore_artifacts_compensate_on_precommit_failure(
    tmp_path: Path,
):
    db = tmp_path / "report-restore-rollback.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restore.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    decisions, digest, snapshot = _locked_plan(
        db,
        tmp_path,
        verify_sha=True,
        entries=entries,
    )
    output = tmp_path / "reports"

    def fail(stage, _context):
        if stage == "before_database_commit":
            raise RuntimeError("forced-precommit")

    with pytest.raises(ReconciliationError, match="forced-precommit"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=output,
            fault_hook=fail,
        )
    assert decisions[0].action == "restore_exact"
    assert not (tmp_path / rel).exists()
    assert not output.exists()
    assert (tmp_path / "before.sqlite").is_file()
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "missing_on_disk"
    finally:
        check.close()


def test_quarantine_evidence_retained_when_reports_and_database_roll_back(
    tmp_path: Path,
):
    db = tmp_path / "quarantine-retained.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/mismatch.png"
    insert_screenshot(conn, rel, b"expected")
    conn.close()
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_bytes(b"wrong")
    _, digest, snapshot = _locked_plan(db, tmp_path, verify_sha=True)
    output = tmp_path / "reports"
    quarantine = tmp_path / "quarantine"

    def fail(stage, _context):
        if stage == "before_database_commit":
            raise RuntimeError("forced-precommit")

    with pytest.raises(ReconciliationError, match="forced-precommit"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=quarantine,
            verify_sha=True,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=output,
            fault_hook=fail,
        )
    artifacts = [item for item in quarantine.rglob("*") if item.is_file()]
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"wrong"
    assert not output.exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "present"
    finally:
        check.close()


def test_preexisting_generation_directory_blocks_before_commit(tmp_path: Path):
    db = tmp_path / "generation-collision.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    conn.close()
    _, digest, snapshot = _locked_plan(db, tmp_path)
    output = tmp_path / "reports"
    generation = output / "runs" / f"00000001-{digest[:16]}"
    generation.mkdir(parents=True)
    with pytest.raises(ReconciliationError, match="already exists|overlaps"):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=output,
        )
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
    finally:
        check.close()


def test_control_namespace_symlink_is_rejected(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    db = tmp_path / "control-link.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(conn, tmp_path)
    conn.close()
    with pytest.raises(ReconciliationError, match="symlink ancestor"):
        validate_apply_control_paths(
            db,
            link / "backup.sqlite",
            tmp_path / "quarantine",
            decisions,
        )


def test_source_unlinked_after_decode_is_marked_missing(tmp_path: Path, monkeypatch):
    db = tmp_path / "unlink-after-open.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/source.png"
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "white").save(source)
    sid = insert_screenshot(conn, rel, source.read_bytes())
    real_open = rlsm_ocr.Image.open

    def open_and_unlink(handle):
        image = real_open(handle)
        original_load = image.load

        def load_then_unlink():
            result = original_load()
            source.unlink(missing_ok=True)
            return result

        image.load = load_then_unlink
        return image

    monkeypatch.setattr(rlsm_ocr, "REPO", tmp_path)
    monkeypatch.setattr(rlsm_ocr.Image, "open", open_and_unlink)
    result = rlsm_ocr.process_screenshot(conn, sid, rel, 1)
    row = conn.execute(
        "SELECT source_availability, availability_detail, ocr_status "
        "FROM screenshots WHERE screenshot_id=?",
        (sid,),
    ).fetchone()
    conn.close()
    assert result["reason"] == "missing_source"
    assert row == ("missing_on_disk", "missing_during_ocr", "pending")


def test_validate_report_paths_is_read_only(tmp_path: Path):
    db = tmp_path / "report-read-only.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(conn, tmp_path)
    conn.close()
    output = tmp_path / "never-created"
    validate_report_output_paths(output, decisions, db_path=db)
    assert not output.exists()


@pytest.mark.parametrize(
    ("stage", "expected_phase", "backup_expected"),
    [
        ("after_final_plan", "control_paths_validated", False),
        ("after_backup_verified", "backup_verified", True),
        ("after_file_actions", "file_actions_installed", True),
        ("after_file_actions_verified", "file_actions_verified", True),
        ("after_database_updates_prepared", "database_updates_prepared", True),
        ("after_reports_prepared", "reports_prepared", True),
        ("after_processing_run_finalized", "processing_run_finalized", True),
        ("before_database_commit", "processing_run_finalized", True),
    ],
)
def test_state_machine_fault_matrix_rolls_back_and_compensates(
    tmp_path: Path,
    stage: str,
    expected_phase: str,
    backup_expected: bool,
):
    db = tmp_path / f"matrix-{stage}.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restore.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / f"candidate-{stage}.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    _, digest, snapshot = _locked_plan(
        db,
        tmp_path,
        verify_sha=True,
        entries=entries,
    )
    backup = tmp_path / f"backup-{stage}.sqlite"
    output = tmp_path / f"reports-{stage}"

    def fail(current_stage, _context):
        if current_stage == stage:
            raise RuntimeError(f"fault:{stage}")

    with pytest.raises(ReconciliationError, match=f"fault:{stage}") as caught:
        reconcile_apply(
            db,
            tmp_path,
            backup_path=backup,
            quarantine_dir=tmp_path / f"quarantine-{stage}",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=output,
            fault_hook=fail,
        )

    receipt = caught.value.receipt
    assert receipt is not None
    assert receipt["state"] == "rolled_back"
    assert receipt["failed_phase"] == expected_phase
    assert receipt["compensation"]["complete"] is True
    assert backup.exists() is backup_expected
    assert not (tmp_path / rel).exists()
    assert not output.exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
        assert check.execute(
            "SELECT source_availability FROM screenshots"
        ).fetchone()[0] == "missing_on_disk"
    finally:
        check.close()


def test_commit_exception_after_durable_commit_is_resolved(
    tmp_path: Path,
    monkeypatch,
):
    db = tmp_path / "commit-resolution.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    conn.close()
    _, digest, snapshot = _locked_plan(db, tmp_path)

    def commit_then_raise(connection):
        connection.commit()
        raise OSError("simulated return-path failure")

    monkeypatch.setattr(
        rlsm_source_availability,
        "_commit_connection",
        commit_then_raise,
    )
    _, _, apply_receipt, _ = reconcile_apply(
        db,
        tmp_path,
        backup_path=tmp_path / "before.sqlite",
        quarantine_dir=tmp_path / "quarantine",
        checked_at="2026-07-30T00:00:00Z",
        expected_plan_digest=digest,
        expected_snapshot_sha256=snapshot,
        report_output_dir=tmp_path / "reports",
    )
    assert apply_receipt["state"] == "committed"
    assert apply_receipt["commit_outcome"] == "resolved_after_commit_exception"
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT status, notes FROM processing_runs WHERE run_id=?",
            (apply_receipt["run_id"],),
        ).fetchone()
        assert row[0] == "completed"
        notes = json.loads(row[1])
        assert notes["receipt_sha256"] == apply_receipt["terminal_receipt"]["receipt_sha256"]
    finally:
        check.close()


def test_commit_exception_before_commit_rolls_back(tmp_path: Path, monkeypatch):
    db = tmp_path / "commit-failure.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restore.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    _, digest, snapshot = _locked_plan(
        db, tmp_path, verify_sha=True, entries=entries
    )

    def fail_before_commit(_connection):
        raise OSError("commit did not begin")

    monkeypatch.setattr(
        rlsm_source_availability,
        "_commit_connection",
        fail_before_commit,
    )
    with pytest.raises(ReconciliationError, match="commit did not begin") as caught:
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=tmp_path / "reports",
        )
    assert caught.value.receipt is not None
    assert caught.value.receipt["state"] == "rolled_back"
    assert not (tmp_path / rel).exists()
    assert not (tmp_path / "reports").exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
    finally:
        check.close()


def test_dry_run_reports_are_content_addressed_and_idempotent(tmp_path: Path):
    db = tmp_path / "dry-reports.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()
    summary = summarize(
        decisions,
        mode="dry-run",
        migration_required=False,
    )
    first = write_reports(tmp_path / "reports", decisions, summary)
    before = [path.read_bytes() for path in first]
    second = write_reports(tmp_path / "reports", decisions, summary)
    assert first == second
    assert [path.read_bytes() for path in second] == before
    assert first[0].parent.name.startswith("dry-run-")
    assert {path.name for path in first[0].parent.iterdir()} == {
        "source_availability_transitions.csv",
        "source_availability_summary.json",
    }


def test_dry_run_report_collision_with_different_bytes_is_blocked(tmp_path: Path):
    db = tmp_path / "dry-report-collision.sqlite"
    conn = create_fresh_db(db)
    insert_screenshot(conn, "data/FR24_baseline/missing.png", b"expected")
    decisions = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-30T00:00:00Z",
    )
    conn.close()
    summary = summarize(
        decisions,
        mode="dry-run",
        migration_required=False,
    )
    paths = write_reports(tmp_path / "reports", decisions, summary)
    paths[0].write_text("tampered", encoding="utf-8")
    with pytest.raises(ReconciliationError, match="bytes differ"):
        write_reports(tmp_path / "reports", decisions, summary)


def test_external_corpus_retarget_during_restore_leaves_no_temp_or_source(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    first = tmp_path / "corpus-a"
    second = tmp_path / "corpus-b"
    first.mkdir()
    second.mkdir()
    link = repo / "data" / "FR24_baseline"
    _symlink_directory(link, first)
    db = tmp_path / "restore-retarget.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/sub/source.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    _, digest, snapshot = _locked_plan(
        db,
        repo,
        verify_sha=True,
        entries=entries,
    )

    def retarget(stage, _context):
        if stage == "before_restore_install":
            link.unlink()
            link.symlink_to(second, target_is_directory=True)

    with pytest.raises(ReconciliationError, match="resolution changed") as caught:
        reconcile_apply(
            db,
            repo,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=tmp_path / "reports",
            fault_hook=retarget,
        )
    assert caught.value.receipt is not None
    assert caught.value.receipt["compensation"]["complete"] is True
    assert not list(first.rglob("*.tmp"))
    assert not list(second.rglob("*.tmp"))
    assert not (first / "sub" / "source.png").exists()
    assert not (second / "sub" / "source.png").exists()
    check = sqlite3.connect(db)
    try:
        assert check.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
    finally:
        check.close()


def test_restore_manifest_binding_change_blocks_before_backup(tmp_path: Path):
    db = tmp_path / "manifest-binding.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/restore.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    manifest = tmp_path / "restore.csv"
    manifest.write_text(
        "rel_path,source_path,sha256\n"
        f"{rel},{candidate},{sha256_file(candidate)}\n",
        encoding="utf-8",
    )
    entries, receipt = (
        rlsm_source_availability.load_restore_manifest_with_receipt(manifest)
    )
    _, digest, snapshot = _locked_plan(
        db,
        tmp_path,
        verify_sha=True,
        entries=entries,
    )
    original = manifest.read_text(encoding="utf-8")
    replacement = tmp_path / "replacement.csv"
    replacement.write_text(original, encoding="utf-8")
    replacement.replace(manifest)

    with pytest.raises(
        ReconciliationError,
        match="restore manifest binding changed",
    ):
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=tmp_path / "reports",
            restore_manifest_path=manifest,
            expected_restore_manifest_receipt=receipt,
        )
    assert not (tmp_path / "before.sqlite").exists()


def test_restore_manifest_symlink_is_rejected(tmp_path: Path):
    real = tmp_path / "real.csv"
    real.write_text("rel_path,source_path,sha256\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    try:
        link.symlink_to(real)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ReconciliationError, match="must not be a symlink"):
        rlsm_source_availability.load_restore_manifest_with_receipt(link)


def test_empty_database_apply_uses_requested_operation_timestamp(tmp_path: Path):
    db = tmp_path / "empty.sqlite"
    conn = create_fresh_db(db)
    conn.close()
    decisions, digest, snapshot = _locked_plan(db, tmp_path)
    assert decisions == []
    stamp = "2026-07-30T01:02:03Z"
    _, _, apply_receipt, _ = reconcile_apply(
        db,
        tmp_path,
        backup_path=tmp_path / "before.sqlite",
        quarantine_dir=tmp_path / "quarantine",
        checked_at=stamp,
        expected_plan_digest=digest,
        expected_snapshot_sha256=snapshot,
        report_output_dir=tmp_path / "reports",
    )
    assert apply_receipt["operation_timestamp"] == stamp
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT started_at, ended_at FROM processing_runs WHERE run_id=?",
            (apply_receipt["run_id"],),
        ).fetchone()
        assert row == (stamp, stamp)
    finally:
        check.close()


def test_external_corpus_retarget_after_restore_link_compensates_resolved_file(
    tmp_path: Path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    first = tmp_path / "corpus-a"
    second = tmp_path / "corpus-b"
    first.mkdir()
    second.mkdir()
    link = repo / "data" / "FR24_baseline"
    _symlink_directory(link, first)
    db = tmp_path / "post-link-retarget.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/source.png"
    data = b"expected"
    insert_screenshot(conn, rel, data, availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(data)
    entries = {rel: RestoreEntry(rel, str(candidate), sha256_file(candidate))}
    _, digest, snapshot = _locked_plan(
        db,
        repo,
        verify_sha=True,
        entries=entries,
    )
    real_link = rlsm_source_availability.os.link

    def link_then_retarget(source, destination, *args, **kwargs):
        result = real_link(source, destination, *args, **kwargs)
        if Path(destination) == first / "source.png":
            link.unlink()
            link.symlink_to(second, target_is_directory=True)
        return result

    monkeypatch.setattr(rlsm_source_availability.os, "link", link_then_retarget)
    with pytest.raises(
        ReconciliationError,
        match="operational source path did not retain",
    ) as caught:
        reconcile_apply(
            db,
            repo,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=tmp_path / "quarantine",
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=tmp_path / "reports",
        )
    assert caught.value.receipt is not None
    assert caught.value.receipt["compensation"]["complete"] is True
    assert not (first / "source.png").exists()
    assert not (second / "source.png").exists()
    assert not list(first.rglob("*.tmp"))
    assert not list(second.rglob("*.tmp"))


def test_quarantine_candidate_inode_change_after_backup_leaves_no_artifacts(
    tmp_path: Path,
):
    db = tmp_path / "quarantine-source-race.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected", availability="missing_on_disk")
    conn.close()
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"wrong")
    entries = {rel: RestoreEntry(rel, str(candidate))}
    _, digest, snapshot = _locked_plan(
        db,
        tmp_path,
        verify_sha=True,
        entries=entries,
    )
    quarantine = tmp_path / "quarantine"

    def replace_candidate(stage, _context):
        if stage == "after_backup_verified":
            replacement = tmp_path / "replacement.png"
            replacement.write_bytes(b"wrong")
            replacement.replace(candidate)

    with pytest.raises(ReconciliationError, match="binding changed") as caught:
        reconcile_apply(
            db,
            tmp_path,
            backup_path=tmp_path / "before.sqlite",
            quarantine_dir=quarantine,
            verify_sha=True,
            restore_entries=entries,
            checked_at="2026-07-30T00:00:00Z",
            expected_plan_digest=digest,
            expected_snapshot_sha256=snapshot,
            report_output_dir=tmp_path / "reports",
            fault_hook=replace_candidate,
        )
    assert caught.value.receipt is not None
    assert caught.value.receipt["compensation"]["complete"] is True
    assert not quarantine.exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_missing_during_retry_resets_failed_ocr_to_pending(
    tmp_path: Path,
    monkeypatch,
):
    db = tmp_path / "retry-missing.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/retry.png"
    sid = insert_screenshot(conn, rel, b"expected", ocr_status="failed")
    conn.close()
    monkeypatch.setattr(rlsm_ocr_parallel, "REPO", tmp_path)
    rlsm_ocr_parallel._worker_init(str(db))
    result = rlsm_ocr_parallel._process_one((sid, rel, 1))
    assert result["status"] == "missing_source"
    check = sqlite3.connect(db)
    try:
        row = check.execute(
            "SELECT source_availability, availability_detail, ocr_status "
            "FROM screenshots WHERE screenshot_id=?",
            (sid,),
        ).fetchone()
        assert row == ("missing_on_disk", "missing_during_ocr", "pending")
    finally:
        check.close()


def test_mark_missing_unknown_screenshot_fails_closed(tmp_path: Path):
    conn = create_fresh_db(tmp_path / "missing-row.sqlite")
    with pytest.raises(ReconciliationError, match="row not found"):
        rlsm_source_availability.mark_missing_during_ocr(conn, 999)
    conn.close()


def test_dry_run_reports_allow_disjoint_quarantine_subdirectory(
    tmp_path: Path,
):
    output = tmp_path / "reports"
    quarantine = output / "quarantine"
    summary = summarize(
        [],
        mode="dry-run",
        migration_required=False,
    )
    summary.update(
        {
            "db_path": str(tmp_path / "rlsm.sqlite"),
            "quarantine_dir": str(quarantine),
            "restore_manifest_path": None,
        }
    )

    csv_path, json_path = write_reports(output, [], summary)

    assert csv_path.is_file()
    assert json_path.is_file()
    assert csv_path.parent.parent.parent == output
    assert json_path.parent == csv_path.parent
    assert not quarantine.exists()



def test_dry_run_reports_ignore_volatile_checked_at_for_content_identity(
    tmp_path: Path,
):
    db = tmp_path / "checked-at.sqlite"
    conn = create_fresh_db(db)
    rel = "data/FR24_baseline/missing.png"
    insert_screenshot(conn, rel, b"expected")
    first = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-31T00:00:00Z",
    )
    second = plan_reconciliation(
        conn,
        tmp_path,
        checked_at="2026-07-31T00:00:01Z",
    )
    conn.close()
    summary_first = summarize(
        first, mode="dry-run", migration_required=False
    )
    summary_second = summarize(
        second, mode="dry-run", migration_required=False
    )

    first_paths = write_reports(tmp_path / "reports", first, summary_first)
    second_paths = write_reports(tmp_path / "reports", second, summary_second)

    assert first_paths == second_paths
    assert first_paths[0].read_bytes() == second_paths[0].read_bytes()
    assert first_paths[1].read_bytes() == second_paths[1].read_bytes()
