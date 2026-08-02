#!/usr/bin/env python3
"""Dry-run-first, locked RLSM source-availability reconciliation."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_source_availability import (  # noqa: E402
    ReconciliationError,
    connect_read_only,
    connection_snapshot_sha256,
    database_snapshot_sha256,
    has_availability_schema,
    load_restore_manifest_with_receipt,
    plan_digest,
    plan_reconciliation,
    reconcile_apply,
    summarize,
    utc_now,
    validate_report_output_paths,
    write_reports,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(repo_root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO / "outputs" / "rlsm_source_availability_reconcile",
    )
    parser.add_argument("--restore-manifest", type=Path)
    parser.add_argument("--verify-sha", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup",
        type=Path,
        help="Required with --apply; destination must not already exist.",
    )
    parser.add_argument("--quarantine-dir", type=Path)
    args = parser.parse_args()

    db_path = args.db.expanduser().resolve()
    repo_root = args.repo_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser()
    quarantine_dir = (
        args.quarantine_dir.expanduser()
        if args.quarantine_dir
        else output_dir / "quarantine"
    )
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    if args.apply and args.backup is None:
        parser.error("--backup is required with --apply")
    if args.restore_manifest and not args.verify_sha:
        args.verify_sha = True

    stamp = utc_now()
    db_file_hash_before = file_sha256(db_path)
    if args.restore_manifest is not None:
        expanded_manifest = args.restore_manifest.expanduser()
        resolved_manifest = (
            expanded_manifest
            if expanded_manifest.is_absolute()
            else Path.cwd() / expanded_manifest
        )
    else:
        resolved_manifest = None
    restore_entries, restore_manifest_receipt = (
        load_restore_manifest_with_receipt(resolved_manifest)
    )

    read_conn = connect_read_only(db_path)
    try:
        migration_required = not has_availability_schema(read_conn)
        preliminary = plan_reconciliation(
            read_conn,
            repo_root,
            verify_sha=args.verify_sha,
            restore_entries=restore_entries,
            checked_at=stamp,
        )
        preliminary_digest = plan_digest(preliminary)
        preliminary_snapshot = connection_snapshot_sha256(read_conn)
    finally:
        read_conn.close()

    resolved_backup = args.backup.expanduser() if args.backup else None
    if args.apply:
        assert resolved_backup is not None
        decisions, backup_receipt, apply_receipt, file_receipts = reconcile_apply(
            db_path,
            repo_root,
            backup_path=resolved_backup,
            quarantine_dir=quarantine_dir,
            verify_sha=args.verify_sha,
            restore_entries=restore_entries,
            checked_at=stamp,
            expected_plan_digest=preliminary_digest,
            expected_snapshot_sha256=preliminary_snapshot,
            git_sha=git_sha(repo_root),
            report_output_dir=output_dir,
            restore_manifest_path=resolved_manifest,
            expected_restore_manifest_receipt=restore_manifest_receipt,
            migration_required=migration_required,
        )
        summary = summarize(
            decisions,
            mode="apply",
            migration_required=migration_required,
            backup=backup_receipt,
            file_receipts=file_receipts,
        )
        summary.update(
            {
                "db_path": str(db_path),
                "repo_root": str(repo_root),
                "quarantine_dir": str(quarantine_dir),
                "restore_manifest_path": (
                    str(resolved_manifest) if resolved_manifest else None
                ),
                "restore_manifest_receipt": restore_manifest_receipt,
                "db_file_sha256_before": db_file_hash_before,
                "db_file_sha256_after": file_sha256(db_path),
                "db_snapshot_sha256_before": preliminary_snapshot,
                "db_snapshot_sha256_after": database_snapshot_sha256(db_path),
                "apply_receipt": apply_receipt,
            }
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        terminal = apply_receipt.get("terminal_receipt", {})
        if isinstance(terminal, dict) and terminal.get("report_generation_dir"):
            print(f"REPORT_GENERATION: {terminal['report_generation_dir']}")
        return 0

    validate_report_output_paths(
        output_dir,
        preliminary,
        db_path=db_path,
        quarantine_dir=quarantine_dir,
        restore_manifest_path=resolved_manifest,
    )
    summary = summarize(
        preliminary,
        mode="dry-run",
        migration_required=migration_required,
    )
    summary.update(
        {
            "db_path": str(db_path),
            "repo_root": str(repo_root),
            "quarantine_dir": str(quarantine_dir),
            "restore_manifest_path": (
                str(resolved_manifest) if resolved_manifest else None
            ),
            "restore_manifest_receipt": restore_manifest_receipt,
            "db_file_sha256_before": db_file_hash_before,
            "db_file_sha256_after": file_sha256(db_path),
            "db_snapshot_sha256_before": preliminary_snapshot,
            "db_snapshot_sha256_after": database_snapshot_sha256(db_path),
        }
    )
    summary["database_file_bytes_unchanged"] = (
        summary["db_file_sha256_before"] == summary["db_file_sha256_after"]
    )
    summary["database_snapshot_unchanged"] = (
        summary["db_snapshot_sha256_before"]
        == summary["db_snapshot_sha256_after"]
    )
    if not summary["database_file_bytes_unchanged"]:
        raise ReconciliationError("dry-run changed database file bytes")
    if not summary["database_snapshot_unchanged"]:
        raise ReconciliationError("dry-run changed database snapshot")
    csv_path, json_path = write_reports(output_dir, preliminary, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    return 0



if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReconciliationError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        if exc.receipt is not None:
            print(
                "FAILURE_RECEIPT="
                + json.dumps(exc.receipt, sort_keys=True, separators=(",", ":")),
                file=sys.stderr,
            )
        raise SystemExit(2) from exc
