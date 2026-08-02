"""RLSM source-file availability and atomic reconciliation.

Historical ingestion validity (``ingest_status``) is independent from whether
an original source is currently reachable. Dry-run planning is read-only. The
mutating path re-plans under a SQLite write reservation, creates and verifies a
snapshot backup, installs source files without overwrite, and compensates any
newly restored files if the database transaction fails.
"""
from __future__ import annotations

import csv
import errno
import hashlib
import io
import json
import os
import sqlite3
import stat
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AVAILABILITY_VALUES = ("present", "missing_on_disk", "restored", "archived")
ELIGIBLE_AVAILABILITY_VALUES = ("present", "restored")
REQUIRED_COLUMNS = {
    "source_availability",
    "availability_checked_at",
    "availability_detail",
    "availability_source",
}
REQUIRED_INDEXES = {"ux_screenshots_rel_path"}
SOURCE_AVAILABILITY_PROTOCOL = "rlsm-source-availability-v1.0"
REPORT_FILENAMES = (
    "source_availability_transitions.csv",
    "source_availability_summary.json",
    "terminal_apply_receipt.json",
)
RECONCILIATION_PHASES = (
    "lock_acquired",
    "final_plan_bound",
    "control_paths_validated",
    "backup_verified",
    "file_actions_installed",
    "file_actions_verified",
    "database_updates_prepared",
    "reports_prepared",
    "processing_run_finalized",
    "precommit_verified",
    "committed",
)
FaultHook = Callable[[str, Mapping[str, object]], None]


class AvailabilitySchemaError(RuntimeError):
    """Raised when OCR or reconciliation sees an unmigrated database."""


class ReconciliationError(RuntimeError):
    """Raised for an invalid or non-atomic reconciliation request."""

    def __init__(
        self,
        message: str,
        *,
        receipt: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = dict(receipt) if receipt is not None else None


class SourceUnavailableError(OSError):
    """Raised when a source cannot be stably opened as one regular file."""


@dataclass(frozen=True)
class RestoreEntry:
    rel_path: str
    source_path: str
    sha256: str | None = None


@dataclass(frozen=True)
class AvailabilityDecision:
    screenshot_id: int
    rel_path: str
    expected_sha256: str
    previous_availability: str
    proposed_availability: str
    previous_detail: str | None
    proposed_detail: str | None
    previous_source: str | None
    proposed_source: str | None
    action: str
    expected_path: str
    resolved_expected_path: str
    candidate_path: str | None = None
    actual_sha256: str | None = None
    bound_path: str | None = None
    bound_resolved_path: str | None = None
    bound_size_bytes: int | None = None
    bound_st_dev: int | None = None
    bound_st_ino: int | None = None
    bound_mtime_ns: int | None = None
    bound_ctime_ns: int | None = None
    checked_at: str | None = None

    @property
    def changes_database(self) -> bool:
        return (
            self.previous_availability != self.proposed_availability
            or self.previous_detail != self.proposed_detail
            or self.previous_source != self.proposed_source
        )


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _receipt_sha256(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _phase_history_through(phase: str) -> list[str]:
    try:
        index = RECONCILIATION_PHASES.index(phase)
    except ValueError as exc:
        raise ReconciliationError(f"unknown reconciliation phase: {phase}") from exc
    return list(RECONCILIATION_PHASES[: index + 1])


def _safe_rel_path(rel_path: str) -> Path:
    if "\x00" in rel_path or "\\" in rel_path:
        raise ReconciliationError(f"unsafe relative path: {rel_path!r}")
    relative = Path(rel_path)
    if (
        not rel_path
        or relative.is_absolute()
        or ".." in relative.parts
        or rel_path != relative.as_posix()
    ):
        raise ReconciliationError(f"unsafe relative path or non-canonical form: {rel_path!r}")
    return relative


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({_quoted_identifier(table)})")
    }


def table_indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA index_list({_quoted_identifier(table)})")
    }


def has_availability_schema(conn: sqlite3.Connection) -> bool:
    return (
        table_columns(conn, "screenshots") >= REQUIRED_COLUMNS
        and table_indexes(conn, "screenshots") >= REQUIRED_INDEXES
    )


def require_availability_schema(conn: sqlite3.Connection) -> None:
    missing_columns = sorted(
        REQUIRED_COLUMNS - table_columns(conn, "screenshots")
    )
    missing_indexes = sorted(
        REQUIRED_INDEXES - table_indexes(conn, "screenshots")
    )
    if missing_columns or missing_indexes:
        details = []
        if missing_columns:
            details.append("columns=" + ",".join(missing_columns))
        if missing_indexes:
            details.append("indexes=" + ",".join(missing_indexes))
        raise AvailabilitySchemaError(
            "RLSM source-availability migration required; missing "
            + "; ".join(details)
            + ". Run scripts/rlsm_reconcile_source_availability.py --apply "
            "with a verified --backup before OCR."
        )


def migrate_schema(conn: sqlite3.Connection) -> list[str]:
    """Idempotently add availability columns and enforce one row per rel_path."""
    columns = table_columns(conn, "screenshots")
    if not columns:
        raise AvailabilitySchemaError("screenshots table does not exist")

    statements = {
        "source_availability": (
            "ALTER TABLE screenshots ADD COLUMN source_availability "
            "TEXT NOT NULL DEFAULT 'present' "
            "CHECK (source_availability IN "
            "('present','missing_on_disk','restored','archived'))"
        ),
        "availability_checked_at": (
            "ALTER TABLE screenshots ADD COLUMN availability_checked_at TEXT"
        ),
        "availability_detail": (
            "ALTER TABLE screenshots ADD COLUMN availability_detail TEXT"
        ),
        "availability_source": (
            "ALTER TABLE screenshots ADD COLUMN availability_source TEXT"
        ),
    }
    added: list[str] = []
    for column, statement in statements.items():
        if column not in columns:
            conn.execute(statement)
            added.append(column)

    duplicates = conn.execute(
        """
        SELECT rel_path, COUNT(*)
        FROM screenshots
        GROUP BY rel_path
        HAVING COUNT(*) != 1
        ORDER BY rel_path
        """
    ).fetchall()
    if duplicates:
        raise ReconciliationError(
            "cannot enforce unique screenshots.rel_path; duplicates="
            + ", ".join(f"{row[0]}:{row[1]}" for row in duplicates)
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_screenshots_rel_path "
        "ON screenshots(rel_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_screenshots_source_availability "
        "ON screenshots(source_availability)"
    )
    return added



def availability_predicate(alias: str = "s") -> str:
    if not alias.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL alias: {alias!r}")
    return f"{alias}.source_availability IN ('present','restored')"


def mark_missing_during_ocr(
    conn: sqlite3.Connection,
    screenshot_id: int,
    *,
    checked_at: str | None = None,
) -> None:
    """Record source disappearance without fabricating an OCR failure."""
    require_availability_schema(conn)
    update = conn.execute(
        """
        UPDATE screenshots
        SET source_availability='missing_on_disk',
            availability_checked_at=?,
            availability_detail='missing_during_ocr',
            availability_source='ocr',
            ocr_status='pending'
        WHERE screenshot_id=?
        """,
        (checked_at or utc_now(), screenshot_id),
    )
    if update.rowcount != 1:
        conn.rollback()
        raise ReconciliationError(
            f"missing OCR source row not found: screenshot_id={screenshot_id}"
        )
    conn.commit()


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _integrity_check(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise ReconciliationError(f"SQLite integrity_check failed: {result}")


def _normalized_sql_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"type": "float", "hex": value.hex()}
    if isinstance(value, bytes):
        return {"type": "blob", "hex": value.hex()}
    raise ReconciliationError(
        f"unsupported SQLite value type during backup verification: {type(value)!r}"
    )


def _table_content_sha256(conn: sqlite3.Connection, table: str) -> str:
    columns = [
        str(row[1])
        for row in conn.execute(f"PRAGMA table_xinfo({_quoted_identifier(table)})")
        if int(row[6]) == 0
    ]
    digest = hashlib.sha256()
    digest.update(_canonical_json({"columns": columns}))
    if not columns:
        return digest.hexdigest()
    selected = ", ".join(_quoted_identifier(column) for column in columns)
    ordered = ", ".join(_quoted_identifier(column) for column in columns)
    query = (
        f"SELECT {selected} FROM {_quoted_identifier(table)} "
        f"ORDER BY {ordered}"
    )
    for row in conn.execute(query):
        digest.update(
            _canonical_json([_normalized_sql_value(value) for value in row])
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _user_table_inventory(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT name, COALESCE(sql, '')
        FROM sqlite_schema
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    inventory: dict[str, dict[str, object]] = {}
    for name, schema_sql in rows:
        table = str(name)
        count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {_quoted_identifier(table)}"
            ).fetchone()[0]
        )
        inventory[table] = {
            "rows": count,
            "schema_sha256": hashlib.sha256(
                str(schema_sql).encode("utf-8")
            ).hexdigest(),
            "content_sha256": _table_content_sha256(conn, table),
        }
    return inventory


def _foreign_key_violations(conn: sqlite3.Connection) -> list[list[object]]:
    return [list(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]


def _snapshot_fingerprint(
    inventory: Mapping[str, Mapping[str, object]],
    foreign_key_violations: Iterable[Iterable[object]],
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "tables": inventory,
                "foreign_key_violations": list(foreign_key_violations),
            }
        )
    ).hexdigest()


def _call_fault_hook(
    fault_hook: FaultHook | None,
    stage: str,
    context: Mapping[str, object],
) -> None:
    if fault_hook is not None:
        fault_hook(stage, context)


def _write_connection_snapshot(conn: sqlite3.Connection, path: Path) -> str:
    """Write the locked connection snapshot to ``path`` and return the method."""
    serialize = getattr(conn, "serialize", None)
    if callable(serialize):
        payload = serialize()
        with path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return "sqlite_serialize"

    # Compatibility fallback for Python builds without Connection.serialize().
    destination = sqlite3.connect(path)
    try:
        destination.execute("PRAGMA foreign_keys = OFF")
        for statement in conn.iterdump():
            stripped = statement.strip()
            if not stripped or stripped in {"BEGIN TRANSACTION;", "COMMIT;"}:
                continue
            destination.execute(statement)
        destination.commit()
    finally:
        destination.close()
    return "sqlite_iterdump"


def _same_inode(path: Path, identity: tuple[int, int]) -> bool:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    return (stat.st_dev, stat.st_ino) == identity


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _stat_identity(value: os.stat_result) -> tuple[int, int]:
    return (int(value.st_dev), int(value.st_ino))


def _stat_binding(value: os.stat_result) -> dict[str, int]:
    return {
        "size_bytes": int(value.st_size),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _binding_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _validate_control_path_topology(path: Path, *, label: str) -> None:
    """Reject symlinked control namespaces and non-directory ancestors."""
    candidate = path.expanduser()
    probe = candidate if candidate.is_absolute() else Path.cwd() / candidate
    parts = probe.parts
    current = Path(parts[0])
    for part in parts[1:-1]:
        current = current / part
        if not _lexists(current):
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ReconciliationError(
                f"{label} has a symlink ancestor: {current}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise ReconciliationError(
                f"{label} has a non-directory ancestor: {current}"
            )
    if _lexists(probe) and probe.is_symlink():
        raise ReconciliationError(f"{label} must not be a symlink: {probe}")


def _validate_expected_path_topology(
    repo_root: Path,
    relative: Path,
) -> tuple[Path, Path]:
    """Allow only the documented corpus-root directory symlink."""
    expected = repo_root / relative
    current = repo_root
    allowed_link = repo_root / "data" / "FR24_baseline"
    for part in relative.parts[:-1]:
        current = current / part
        if not _lexists(current):
            break
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            if current != allowed_link:
                raise ReconciliationError(
                    f"unexpected symlink in screenshot path: {current}"
                )
            target = current.resolve(strict=True)
            if not target.is_dir():
                raise ReconciliationError(
                    f"external corpus symlink target is not a directory: {target}"
                )
        elif not stat.S_ISDIR(info.st_mode):
            raise ReconciliationError(
                f"screenshot path has a non-directory ancestor: {current}"
            )
    if _lexists(expected):
        info = expected.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ReconciliationError(
                f"screenshot leaf must not be a symlink: {expected}"
            )
        if not stat.S_ISREG(info.st_mode):
            raise ReconciliationError(
                f"screenshot path is not a regular file: {expected}"
            )
    return expected, expected.resolve(strict=False)


def _snapshot_regular_file(
    path: Path,
    *,
    hash_content: bool,
    label: str,
) -> dict[str, object]:
    """Bind one stable regular-file inode through its operational pathname."""
    if not _lexists(path):
        raise ReconciliationError(f"{label} missing: {path}")
    if path.is_symlink():
        raise ReconciliationError(f"{label} must not be a symlink: {path}")
    resolved_before = path.resolve(strict=True)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ReconciliationError(f"unable to open {label}: {path}: {exc}") from exc
    digest = hashlib.sha256() if hash_content else None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReconciliationError(f"{label} is not a regular file: {path}")
        if digest is not None:
            while True:
                chunk = os.read(fd, 4 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if _binding_tuple(before) != _binding_tuple(after):
        raise ReconciliationError(f"{label} changed while being inspected: {path}")
    if not _lexists(path) or path.is_symlink():
        raise ReconciliationError(f"{label} pathname changed while inspected: {path}")
    resolved_after = path.resolve(strict=True)
    current = path.stat()
    if resolved_before != resolved_after or _stat_identity(current) != _stat_identity(after):
        raise ReconciliationError(
            f"{label} resolved target changed while inspected: {path}"
        )
    result: dict[str, object] = {
        "path": str(path),
        "resolved_path": str(resolved_after),
        **_stat_binding(after),
    }
    result["sha256"] = digest.hexdigest() if digest is not None else None
    return result


def _decision_binding(decision: AvailabilityDecision) -> dict[str, object]:
    return {
        "path": decision.bound_path,
        "resolved_path": decision.bound_resolved_path,
        "sha256": decision.actual_sha256,
        "size_bytes": decision.bound_size_bytes,
        "st_dev": decision.bound_st_dev,
        "st_ino": decision.bound_st_ino,
        "mtime_ns": decision.bound_mtime_ns,
        "ctime_ns": decision.bound_ctime_ns,
    }


def _verify_decision_binding(
    decision: AvailabilityDecision,
    *,
    label: str,
) -> None:
    if decision.bound_path is None:
        raise ReconciliationError(f"{label} decision lacks a file binding")
    current = _snapshot_regular_file(
        Path(decision.bound_path),
        hash_content=decision.actual_sha256 is not None,
        label=label,
    )
    planned = _decision_binding(decision)
    for key in (
        "resolved_path",
        "size_bytes",
        "st_dev",
        "st_ino",
        "mtime_ns",
        "ctime_ns",
    ):
        if current.get(key) != planned.get(key):
            raise ReconciliationError(
                f"{label} binding changed: key={key}, "
                f"planned={planned.get(key)}, current={current.get(key)}"
            )
    if decision.actual_sha256 is not None and current.get("sha256") != decision.actual_sha256:
        raise ReconciliationError(
            f"{label} SHA-256 changed: planned={decision.actual_sha256}, "
            f"current={current.get('sha256')}"
        )


@contextmanager
def open_stable_source(path: Path) -> Iterator[object]:
    """Open one stable regular source and bind its operational pathname."""
    resolved_before = path.resolve(strict=False)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ESTALE}:
            raise FileNotFoundError(path) from exc
        if exc.errno == errno.ELOOP:
            raise SourceUnavailableError(f"source leaf is a symlink: {path}") from exc
        raise
    handle = os.fdopen(fd, "rb", closefd=True)
    before = os.fstat(handle.fileno())
    if not stat.S_ISREG(before.st_mode):
        handle.close()
        raise SourceUnavailableError(f"source is not a regular file: {path}")
    try:
        yield handle
        after = os.fstat(handle.fileno())
        if _binding_tuple(before) != _binding_tuple(after):
            raise SourceUnavailableError(f"source changed while decoding: {path}")
        if not _lexists(path) or path.is_symlink():
            raise SourceUnavailableError(
                f"source pathname disappeared or became a symlink: {path}"
            )
        current = path.stat()
        resolved_after = path.resolve(strict=True)
        if (
            _stat_identity(current) != _stat_identity(after)
            or resolved_after != resolved_before
        ):
            raise SourceUnavailableError(
                f"source pathname retargeted while decoding: {path}"
            )
    finally:
        handle.close()



def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _paths_overlap(left: Path, right: Path) -> bool:
    """Return true when either resolved path is the other or its descendant."""
    left_resolved = _resolved(left)
    right_resolved = _resolved(right)
    return (
        left_resolved == right_resolved
        or left_resolved in right_resolved.parents
        or right_resolved in left_resolved.parents
    )


def _database_control_paths(db_path: Path) -> tuple[Path, ...]:
    resolved = _resolved(db_path)
    return (
        resolved,
        Path(f"{resolved}-wal"),
        Path(f"{resolved}-shm"),
        Path(f"{resolved}-journal"),
    )


def _validate_database_backup_path(db_path: Path, backup_path: Path) -> None:
    _validate_control_path_topology(backup_path, label="backup destination")
    backup = _resolved(backup_path)
    for reserved in _database_control_paths(db_path):
        if _paths_overlap(backup, reserved):
            raise ReconciliationError(
                "backup destination overlaps the database or a SQLite sidecar: "
                f"backup={backup}, reserved={reserved}"
            )



def validate_apply_control_paths(
    db_path: Path,
    backup_path: Path,
    quarantine_dir: Path,
    decisions: Iterable[AvailabilityDecision],
) -> None:
    """Reject control paths that could occupy or contain evidentiary paths."""
    _validate_control_path_topology(backup_path, label="backup destination")
    _validate_control_path_topology(quarantine_dir, label="quarantine directory")
    backup = _resolved(backup_path)
    quarantine = _resolved(quarantine_dir)
    _validate_database_backup_path(db_path, backup)

    if _paths_overlap(backup, quarantine):
        raise ReconciliationError(
            "backup destination overlaps quarantine directory: "
            f"backup={backup}, quarantine={quarantine}"
        )

    protected: list[tuple[str, Path]] = []
    for decision in decisions:
        protected.extend(
            (
                ("expected source", Path(decision.expected_path)),
                ("resolved expected source", Path(decision.resolved_expected_path)),
            )
        )
        if decision.candidate_path:
            protected.append(("restore candidate", Path(decision.candidate_path)))

    for label, protected_path in protected:
        resolved = _resolved(protected_path)
        if _paths_overlap(backup, resolved):
            raise ReconciliationError(
                f"backup destination overlaps {label}: "
                f"backup={backup}, protected={resolved}"
            )
        if _paths_overlap(quarantine, resolved):
            raise ReconciliationError(
                f"quarantine directory overlaps {label}: "
                f"quarantine={quarantine}, protected={resolved}"
            )

    for reserved in _database_control_paths(db_path):
        if _paths_overlap(quarantine, reserved):
            raise ReconciliationError(
                "quarantine directory overlaps the database or a SQLite sidecar: "
                f"quarantine={quarantine}, reserved={reserved}"
            )



def validate_report_output_paths(
    output_dir: Path,
    decisions: Iterable[AvailabilityDecision],
    *,
    db_path: Path | None = None,
    backup_path: Path | None = None,
    quarantine_dir: Path | None = None,
    restore_manifest_path: Path | None = None,
    generation_dir: Path | None = None,
    allow_existing_report_files: bool = False,
) -> None:
    """Read-only validation of report and terminal-receipt namespaces."""
    _validate_control_path_topology(output_dir, label="report output directory")
    output = _resolved(output_dir)
    if _lexists(output) and not output.is_dir():
        raise ReconciliationError(
            f"report output path is not a directory: {output}"
        )
    report_root = _resolved(generation_dir) if generation_dir else output
    reports = tuple(report_root / name for name in REPORT_FILENAMES)
    for report in reports:
        if _lexists(report):
            if not allow_existing_report_files:
                raise ReconciliationError(
                    f"immutable report destination already exists: {report}"
                )
            if report.is_symlink() or not report.is_file():
                raise ReconciliationError(
                    f"existing report destination is not a regular file: {report}"
                )

    protected: list[tuple[str, Path]] = []
    if db_path is not None:
        protected.extend(
            ("database control path", item)
            for item in _database_control_paths(db_path)
        )
    if backup_path is not None:
        protected.append(("backup file", _resolved(backup_path)))
    if quarantine_dir is not None:
        protected.append(("quarantine directory", _resolved(quarantine_dir)))
    if restore_manifest_path is not None:
        protected.append(("restore manifest", _resolved(restore_manifest_path)))
    for decision in decisions:
        protected.extend(
            (
                ("expected source", Path(decision.expected_path)),
                ("resolved expected source", Path(decision.resolved_expected_path)),
            )
        )
        if decision.candidate_path:
            protected.append(("restore candidate", Path(decision.candidate_path)))

    for label, protected_path in protected:
        resolved = _resolved(protected_path)
        if output == resolved or resolved in output.parents:
            raise ReconciliationError(
                f"report output directory is at or below {label}: "
                f"output={output}, protected={resolved}"
            )
        if generation_dir is not None and _paths_overlap(report_root, resolved):
            raise ReconciliationError(
                f"report generation namespace overlaps {label}: "
                f"generation={report_root}, protected={resolved}"
            )
        for report in reports:
            if _paths_overlap(report, resolved):
                raise ReconciliationError(
                    f"report file overlaps {label}: "
                    f"report={report}, protected={resolved}"
                )



def connection_snapshot_sha256(conn: sqlite3.Connection) -> str:
    """Hash the complete logical SQLite snapshot visible to ``conn``."""
    serialize = getattr(conn, "serialize", None)
    if callable(serialize):
        return hashlib.sha256(serialize()).hexdigest()
    inventory = _user_table_inventory(conn)
    foreign_keys = _foreign_key_violations(conn)
    return _snapshot_fingerprint(inventory, foreign_keys)


def backup_database_locked(
    conn: sqlite3.Connection,
    db_path: Path,
    backup_path: Path,
    *,
    fault_hook: FaultHook | None = None,
) -> dict[str, object]:
    """Create and verify a durable backup under ``BEGIN IMMEDIATE``."""
    if not conn.in_transaction:
        raise ReconciliationError("backup requires an active write reservation")

    db_path = db_path.resolve()
    _validate_database_backup_path(db_path, backup_path)
    backup_path = backup_path.resolve(strict=False)
    database_rows = conn.execute("PRAGMA database_list").fetchall()
    main_paths = [
        Path(row[2]).resolve() for row in database_rows if row[1] == "main"
    ]
    if main_paths != [db_path]:
        raise ReconciliationError(
            f"locked connection does not target requested database: {main_paths}"
        )
    if _lexists(backup_path):
        raise ReconciliationError(
            f"backup destination already exists: {backup_path}"
        )

    created_directories = _ensure_directory_chain(
        backup_path.parent,
        None,
        allow_symlink_ancestor=False,
    )
    source_inventory = _user_table_inventory(conn)
    source_fk = _foreign_key_violations(conn)
    source_fingerprint = _snapshot_fingerprint(source_inventory, source_fk)
    _integrity_check(conn)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{backup_path.name}.",
        suffix=".tmp",
        dir=backup_path.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    created_identity: tuple[int, int] | None = None
    try:
        method = _write_connection_snapshot(conn, temp_path)
        temp_binding = _snapshot_regular_file(
            temp_path,
            hash_content=True,
            label="backup temporary snapshot",
        )
        generated_sha = str(temp_binding["sha256"])
        try:
            os.link(temp_path, backup_path)
        except FileExistsError as exc:
            raise ReconciliationError(
                f"backup destination appeared during creation: {backup_path}"
            ) from exc
        _fsync_directory(backup_path.parent)
        created_stat = backup_path.stat()
        created_identity = _stat_identity(created_stat)
        temp_path.unlink()

        _call_fault_hook(
            fault_hook,
            "after_backup_install_before_verify",
            {"backup_path": str(backup_path), "sha256": generated_sha},
        )

        destination = connect_read_only(backup_path)
        try:
            _integrity_check(destination)
            backup_inventory = _user_table_inventory(destination)
            backup_fk = _foreign_key_violations(destination)
        finally:
            destination.close()

        if source_inventory != backup_inventory:
            raise ReconciliationError(
                "backup user-table inventory mismatch: "
                f"source={source_inventory}, backup={backup_inventory}"
            )
        if source_fk != backup_fk:
            raise ReconciliationError(
                "backup foreign-key state mismatch: "
                f"source={source_fk}, backup={backup_fk}"
            )
        verified = _snapshot_regular_file(
            backup_path,
            hash_content=True,
            label="verified backup",
        )
        if verified["sha256"] != generated_sha:
            raise ReconciliationError(
                f"backup hash changed during verification: {backup_path}"
            )

        return {
            "path": str(backup_path),
            "sha256": verified["sha256"],
            "size_bytes": verified["size_bytes"],
            "st_dev": verified["st_dev"],
            "st_ino": verified["st_ino"],
            "method": method,
            "tables": backup_inventory,
            "foreign_key_violations": backup_fk,
            "snapshot_fingerprint": source_fingerprint,
            "integrity_check": "ok",
            "write_reservation": "BEGIN IMMEDIATE",
            "created_directories": created_directories,
        }
    except Exception:
        if created_identity is not None and _same_inode(backup_path, created_identity):
            backup_path.unlink(missing_ok=True)
            _fsync_directory(backup_path.parent)
        for entry in reversed(created_directories):
            directory = Path(str(entry["path"]))
            if _lexists(directory) and _same_inode(
                directory,
                (int(entry["st_dev"]), int(entry["st_ino"])),
            ):
                with suppress(OSError):
                    directory.rmdir()
        raise
    finally:
        temp_path.unlink(missing_ok=True)



def backup_database(db_path: Path, backup_path: Path) -> dict[str, object]:
    """Create a standalone verified backup under a write reservation."""
    conn = sqlite3.connect(db_path.resolve(), timeout=30.0, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        receipt = backup_database_locked(conn, db_path, backup_path)
        conn.rollback()
        return receipt
    finally:
        conn.close()


def _parse_restore_manifest_payload(
    path: Path,
    payload: bytes,
) -> dict[str, RestoreEntry]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReconciliationError(
            f"restore manifest is not valid UTF-8: {path}"
        ) from exc
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ReconciliationError(
                f"restore manifest JSON is invalid: {path}: {exc}"
            ) from exc
        if isinstance(parsed, dict):
            rows = parsed.get("entries", [])
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ReconciliationError(
                "restore manifest JSON must be a list or entries object"
            )
    else:
        rows = list(csv.DictReader(io.StringIO(text, newline="")))

    entries: dict[str, RestoreEntry] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ReconciliationError("restore manifest entries must be objects")
        rel_path = str(raw.get("rel_path", "")).strip()
        source_path = str(raw.get("source_path", "")).strip()
        manifest_sha = str(raw.get("sha256", "")).strip().lower() or None
        _safe_rel_path(rel_path)
        if not source_path:
            raise ReconciliationError(
                "each restore entry requires rel_path and source_path"
            )
        if manifest_sha is not None and (
            len(manifest_sha) != 64
            or any(char not in "0123456789abcdef" for char in manifest_sha)
        ):
            raise ReconciliationError(
                f"invalid restore manifest SHA-256 for {rel_path}: {manifest_sha}"
            )
        source = Path(source_path).expanduser()
        source = (
            (path.parent / source).resolve()
            if not source.is_absolute()
            else source.resolve()
        )
        if rel_path in entries:
            raise ReconciliationError(f"duplicate restore rel_path: {rel_path}")
        entries[rel_path] = RestoreEntry(rel_path, str(source), manifest_sha)
    return entries


def _restore_entries_digest(
    entries: Mapping[str, RestoreEntry],
) -> str:
    payload = [
        asdict(entries[rel_path])
        for rel_path in sorted(entries)
    ]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def load_restore_manifest_with_receipt(
    path: Path | None,
) -> tuple[dict[str, RestoreEntry], dict[str, object] | None]:
    """Load one path-bound manifest and return its provenance receipt."""
    if path is None:
        return {}, None
    expanded = path.expanduser()
    manifest_path = (
        expanded
        if expanded.is_absolute()
        else Path.cwd() / expanded
    )
    if not _lexists(manifest_path):
        raise ReconciliationError(
            f"restore manifest not found: {manifest_path}"
        )
    if manifest_path.is_symlink():
        raise ReconciliationError(
            f"restore manifest must not be a symlink: {manifest_path}"
        )
    try:
        with open_stable_source(manifest_path) as handle:
            info = os.fstat(handle.fileno())
            payload = handle.read()
    except (FileNotFoundError, SourceUnavailableError, OSError) as exc:
        raise ReconciliationError(
            f"restore manifest could not be read stably: {manifest_path}: {exc}"
        ) from exc
    entries = _parse_restore_manifest_payload(manifest_path, payload)
    receipt: dict[str, object] = {
        "path": str(manifest_path),
        "resolved_path": str(manifest_path.resolve(strict=True)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        **_stat_binding(info),
        "entries_digest": _restore_entries_digest(entries),
        "entry_count": len(entries),
    }
    return entries, receipt


def load_restore_manifest(path: Path | None) -> dict[str, RestoreEntry]:
    entries, _receipt = load_restore_manifest_with_receipt(path)
    return entries


def _verify_restore_manifest_binding(
    path: Path,
    expected_entries: Mapping[str, RestoreEntry],
    expected_receipt: Mapping[str, object] | None,
) -> dict[str, object]:
    current_entries, current_receipt = load_restore_manifest_with_receipt(path)
    assert current_receipt is not None
    if current_entries != dict(expected_entries):
        raise ReconciliationError(
            "restore manifest entries changed before locked apply: "
            f"path={path}"
        )
    if expected_receipt is not None:
        for key in (
            "path",
            "resolved_path",
            "sha256",
            "size_bytes",
            "st_dev",
            "st_ino",
            "mtime_ns",
            "ctime_ns",
            "entries_digest",
            "entry_count",
        ):
            if current_receipt.get(key) != expected_receipt.get(key):
                raise ReconciliationError(
                    "restore manifest binding changed before locked apply: "
                    f"key={key}, expected={expected_receipt.get(key)}, "
                    f"current={current_receipt.get(key)}"
                )
    return current_receipt


def _read_screenshot_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    columns = table_columns(conn, "screenshots")
    availability = (
        "source_availability"
        if "source_availability" in columns
        else "'present' AS source_availability"
    )
    checked = (
        "availability_checked_at"
        if "availability_checked_at" in columns
        else "NULL AS availability_checked_at"
    )
    detail = (
        "availability_detail"
        if "availability_detail" in columns
        else "NULL AS availability_detail"
    )
    source = (
        "availability_source"
        if "availability_source" in columns
        else "NULL AS availability_source"
    )
    return conn.execute(
        f"""
        SELECT screenshot_id, rel_path, sha256, ingest_status, ocr_status,
               {availability}, {checked}, {detail}, {source}
        FROM screenshots
        ORDER BY screenshot_id
        """
    ).fetchall()


def plan_reconciliation(
    conn: sqlite3.Connection,
    repo_root: Path,
    *,
    verify_sha: bool = False,
    restore_entries: Mapping[str, RestoreEntry] | None = None,
    checked_at: str | None = None,
) -> list[AvailabilityDecision]:
    """Build a deterministic, read-only plan with explicit path bindings."""
    repo_root = repo_root.resolve()
    restore_entries = restore_entries or {}
    stamp = checked_at or utc_now()
    decisions: list[AvailabilityDecision] = []
    rows = _read_screenshot_rows(conn)
    rel_paths = [str(row["rel_path"]) for row in rows]

    counts: dict[str, int] = {}
    folded: dict[str, str] = {}
    for rel_path in rel_paths:
        _safe_rel_path(rel_path)
        counts[rel_path] = counts.get(rel_path, 0) + 1
        key = rel_path.casefold()
        prior = folded.get(key)
        if prior is not None and prior != rel_path:
            raise ReconciliationError(
                "screenshots contains case-folding rel_path aliases: "
                f"{prior}, {rel_path}"
            )
        folded[key] = rel_path
    duplicates = sorted(path for path, count in counts.items() if count != 1)
    if duplicates:
        raise ReconciliationError(
            "screenshots contains duplicate rel_path values: "
            + ", ".join(duplicates)
        )

    known_paths = set(rel_paths)
    unknown_entries = sorted(set(restore_entries) - known_paths)
    if unknown_entries:
        raise ReconciliationError(
            "restore manifest contains unknown screenshots rel_path values: "
            + ", ".join(unknown_entries)
        )
    candidate_paths: dict[str, str] = {}
    for rel_path, entry in sorted(restore_entries.items()):
        key = str(Path(entry.source_path).resolve(strict=False)).casefold()
        prior = candidate_paths.get(key)
        if prior is not None:
            raise ReconciliationError(
                "restore manifest reuses one candidate path: "
                f"{prior}, {rel_path} -> {entry.source_path}"
            )
        candidate_paths[key] = rel_path

    resolved_targets: dict[str, str] = {}
    physical_targets: dict[tuple[int, int], str] = {}
    candidate_physical: dict[tuple[int, int], str] = {}

    for row in rows:
        sid = int(row["screenshot_id"])
        rel_path = str(row["rel_path"])
        expected_sha = str(row["sha256"]).lower()
        if len(expected_sha) != 64 or any(
            char not in "0123456789abcdef" for char in expected_sha
        ):
            raise ReconciliationError(
                f"screenshots row has invalid SHA-256: {sid}:{expected_sha}"
            )
        previous = str(row["source_availability"] or "present")
        if previous not in AVAILABILITY_VALUES:
            raise ReconciliationError(
                f"screenshots row has invalid availability: {sid}:{previous}"
            )
        previous_detail = row["availability_detail"]
        previous_source = row["availability_source"]
        relative = _safe_rel_path(rel_path)
        expected_path, resolved_expected = _validate_expected_path_topology(
            repo_root,
            relative,
        )
        resolved_key = str(resolved_expected).casefold()
        prior_resolved = resolved_targets.get(resolved_key)
        if prior_resolved is not None:
            raise ReconciliationError(
                "screenshots paths resolve to the same source target: "
                f"{prior_resolved}, {rel_path} -> {resolved_expected}"
            )
        resolved_targets[resolved_key] = rel_path

        entry = restore_entries.get(rel_path)
        if entry is not None and _lexists(expected_path):
            raise ReconciliationError(
                "restore manifest entry is unused because expected source already "
                f"exists: {rel_path}"
            )

        proposed = previous
        detail = previous_detail
        source = previous_source
        action = "no_change"
        candidate_path: str | None = None
        actual_sha: str | None = None
        binding: dict[str, object] | None = None

        if _lexists(expected_path):
            should_hash = verify_sha or previous in {
                "missing_on_disk",
                "restored",
                "archived",
            }
            binding = _snapshot_regular_file(
                expected_path,
                hash_content=should_hash,
                label="expected source",
            )
            identity = (int(binding["st_dev"]), int(binding["st_ino"]))
            prior_physical = physical_targets.get(identity)
            if prior_physical is not None:
                raise ReconciliationError(
                    "screenshots rows reference the same physical source inode: "
                    f"{prior_physical}, {rel_path}"
                )
            physical_targets[identity] = rel_path
            actual_sha = (
                str(binding["sha256"])
                if binding.get("sha256") is not None
                else None
            )
            if should_hash:
                if actual_sha == expected_sha:
                    proposed = (
                        "restored"
                        if previous in {"missing_on_disk", "restored", "archived"}
                        else "present"
                    )
                    if previous == "restored":
                        detail = previous_detail
                        source = previous_source
                    else:
                        detail = "sha256_verified"
                        source = "reconcile"
                    action = "verified_on_disk"
                else:
                    proposed = "missing_on_disk"
                    detail = "sha256_mismatch_on_disk"
                    source = "reconcile"
                    action = "quarantine_existing_mismatch"
            else:
                proposed = "present"
                detail = "present_on_disk"
                source = "reconcile"
                action = "present_on_disk"
        elif entry is not None:
            candidate = Path(entry.source_path)
            candidate_path = str(candidate)
            if not _lexists(candidate):
                proposed = "missing_on_disk"
                detail = "restore_candidate_missing"
                source = "restore_manifest"
                action = "candidate_missing"
            else:
                binding = _snapshot_regular_file(
                    candidate,
                    hash_content=True,
                    label="restore candidate",
                )
                identity = (int(binding["st_dev"]), int(binding["st_ino"]))
                prior_candidate = candidate_physical.get(identity)
                if prior_candidate is not None:
                    raise ReconciliationError(
                        "restore manifest reuses one physical candidate inode: "
                        f"{prior_candidate}, {rel_path}"
                    )
                candidate_physical[identity] = rel_path
                actual_sha = str(binding["sha256"])
                manifest_sha_ok = entry.sha256 is None or entry.sha256 == actual_sha
                if actual_sha == expected_sha and manifest_sha_ok:
                    proposed = "restored"
                    detail = "restored_sha256_verified"
                    source = "restore_manifest"
                    action = "restore_exact"
                else:
                    proposed = "missing_on_disk"
                    detail = "restore_candidate_sha256_mismatch"
                    source = "restore_manifest"
                    action = "quarantine_candidate_mismatch"
        elif previous == "archived":
            action = "archived_absent"
        else:
            proposed = "missing_on_disk"
            detail = "path_missing"
            source = "reconcile"
            action = "mark_missing"

        decisions.append(
            AvailabilityDecision(
                screenshot_id=sid,
                rel_path=rel_path,
                expected_sha256=expected_sha,
                previous_availability=previous,
                proposed_availability=proposed,
                previous_detail=previous_detail,
                proposed_detail=detail,
                previous_source=previous_source,
                proposed_source=source,
                action=action,
                expected_path=str(expected_path),
                resolved_expected_path=str(resolved_expected),
                candidate_path=candidate_path,
                actual_sha256=actual_sha,
                bound_path=(str(binding["path"]) if binding else None),
                bound_resolved_path=(
                    str(binding["resolved_path"]) if binding else None
                ),
                bound_size_bytes=(int(binding["size_bytes"]) if binding else None),
                bound_st_dev=(int(binding["st_dev"]) if binding else None),
                bound_st_ino=(int(binding["st_ino"]) if binding else None),
                bound_mtime_ns=(int(binding["mtime_ns"]) if binding else None),
                bound_ctime_ns=(int(binding["ctime_ns"]) if binding else None),
                checked_at=stamp,
            )
        )
    return decisions



def plan_digest(decisions: Iterable[AvailabilityDecision]) -> str:
    payload = []
    for decision in sorted(decisions, key=lambda item: item.screenshot_id):
        row = asdict(decision)
        row.pop("checked_at", None)
        payload.append(row)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()



def _ensure_directory_chain(
    path: Path,
    compensation: list[dict[str, object]] | None,
    *,
    allow_symlink_ancestor: bool,
) -> list[dict[str, object]]:
    missing: list[Path] = []
    current = path
    while not _lexists(current):
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    if _lexists(current):
        if current.is_symlink() and not allow_symlink_ancestor:
            raise ReconciliationError(
                f"directory chain contains a symlink: {current}"
            )
        if not current.is_dir():
            raise ReconciliationError(
                f"directory chain has a non-directory ancestor: {current}"
            )
    created: list[dict[str, object]] = []
    for directory in reversed(missing):
        directory.mkdir()
        info = directory.stat()
        entry = {
            "kind": "directory",
            "path": str(directory),
            "st_dev": info.st_dev,
            "st_ino": info.st_ino,
        }
        created.append(entry)
        if compensation is not None:
            compensation.append(entry)
        _fsync_directory(directory.parent)
    return created



def _install_bytes_no_overwrite(
    destination: Path,
    payload: bytes,
    *,
    action: str,
    compensation: list[dict[str, object]],
) -> dict[str, object]:
    if _lexists(destination):
        raise ReconciliationError(
            f"immutable artifact destination already exists: {destination}"
        )
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        digest = sha256_file(temp_path)
        os.link(temp_path, destination)
        info = destination.stat()
        _fsync_directory(destination.parent)
        receipt = {
            "action": action,
            "path": str(destination),
            "sha256": digest,
            "size_bytes": info.st_size,
            "st_dev": info.st_dev,
            "st_ino": info.st_ino,
        }
        compensation.append({"kind": "file", **receipt})
        return receipt
    except FileExistsError as exc:
        raise ReconciliationError(
            f"immutable artifact destination appeared: {destination}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _csv_report_bytes(
    decisions: Iterable[AvailabilityDecision],
    *,
    include_checked_at: bool = True,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=REPORT_FIELDS)
    writer.writeheader()
    for decision in sorted(decisions, key=lambda item: item.screenshot_id):
        row = asdict(decision)
        if not include_checked_at:
            row["checked_at"] = None
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _json_report_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _publish_apply_reports(
    output_dir: Path,
    decisions: list[AvailabilityDecision],
    summary: dict[str, object],
    terminal_receipt: dict[str, object],
    *,
    run_id: int,
    plan_digest_value: str,
    db_path: Path,
    backup_path: Path,
    quarantine_dir: Path,
    restore_manifest_path: Path | None,
    compensation: list[dict[str, object]],
) -> tuple[Path, list[dict[str, object]], dict[str, object]]:
    generation_dir = (
        output_dir
        / "runs"
        / f"{run_id:08d}-{plan_digest_value[:16]}"
    )
    validate_report_output_paths(
        output_dir,
        decisions,
        db_path=db_path,
        backup_path=backup_path,
        quarantine_dir=quarantine_dir,
        restore_manifest_path=restore_manifest_path,
        generation_dir=generation_dir,
    )
    _ensure_directory_chain(
        generation_dir.parent,
        compensation,
        allow_symlink_ancestor=False,
    )
    if _lexists(generation_dir):
        raise ReconciliationError(
            "immutable report generation directory already exists: "
            f"{generation_dir}"
        )
    generation_dir.mkdir()
    generation_stat = generation_dir.stat()
    compensation.append(
        {
            "kind": "directory",
            "path": str(generation_dir),
            "st_dev": generation_stat.st_dev,
            "st_ino": generation_stat.st_ino,
        }
    )
    _fsync_directory(generation_dir.parent)

    csv_receipt = _install_bytes_no_overwrite(
        generation_dir / REPORT_FILENAMES[0],
        _csv_report_bytes(decisions),
        action="report_transitions",
        compensation=compensation,
    )
    summary_receipt = _install_bytes_no_overwrite(
        generation_dir / REPORT_FILENAMES[1],
        _json_report_bytes(summary),
        action="report_summary",
        compensation=compensation,
    )
    terminal_payload = {
        **terminal_receipt,
        "state": "commit_prepared",
        "phase_history": _phase_history_through("reports_prepared"),
        "report_generation_dir": str(generation_dir),
        "reports": [csv_receipt, summary_receipt],
        "commit_authority": {
            "table": "processing_runs",
            "run_id": run_id,
            "required_status": "completed",
            "matching_plan_digest": plan_digest_value,
        },
    }
    terminal_payload["receipt_sha256"] = _receipt_sha256(terminal_payload)
    terminal_file_receipt = _install_bytes_no_overwrite(
        generation_dir / REPORT_FILENAMES[2],
        _json_report_bytes(terminal_payload),
        action="terminal_apply_receipt",
        compensation=compensation,
    )
    receipts = [csv_receipt, summary_receipt, terminal_file_receipt]
    terminal_payload["terminal_receipt_file"] = terminal_file_receipt
    return generation_dir, receipts, terminal_payload

def _open_bound_source_handle(
    decision: AvailabilityDecision,
    *,
    label: str,
) -> object:
    """Open the exact planned source inode and return one binary handle."""
    if decision.bound_path is None:
        raise ReconciliationError(f"{label} decision lacks a file binding")
    source = Path(decision.bound_path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise ReconciliationError(
            f"unable to open bound {label}: {source}: {exc}"
        ) from exc
    handle = os.fdopen(fd, "rb", closefd=True)
    try:
        info = os.fstat(handle.fileno())
        planned = (
            decision.bound_st_dev,
            decision.bound_st_ino,
            decision.bound_size_bytes,
            decision.bound_mtime_ns,
            decision.bound_ctime_ns,
        )
        if _binding_tuple(info) != tuple(int(value) for value in planned):
            raise ReconciliationError(
                f"{label} binding changed before copy: {source}"
            )
        if source.resolve(strict=True) != Path(
            str(decision.bound_resolved_path)
        ):
            raise ReconciliationError(
                f"{label} resolved target changed before copy: {source}"
            )
        return handle
    except Exception:
        handle.close()
        raise


def _copy_bound_source_to_temp(
    decision: AvailabilityDecision,
    destination_dir: Path,
    prefix: str,
    *,
    label: str,
) -> tuple[Path, str]:
    """Copy one planned source descriptor and verify path stability."""
    source = Path(str(decision.bound_path))
    handle = _open_bound_source_handle(decision, label=label)
    fd, temp_name = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp",
        dir=destination_dir,
    )
    temp_path = Path(temp_name)
    digest = hashlib.sha256()
    try:
        with handle, os.fdopen(fd, "wb", closefd=True) as destination:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                destination.write(chunk)
                digest.update(chunk)
            destination.flush()
            os.fsync(destination.fileno())
            after = os.fstat(handle.fileno())
        planned_binding = (
            int(decision.bound_st_dev),
            int(decision.bound_st_ino),
            int(decision.bound_size_bytes),
            int(decision.bound_mtime_ns),
            int(decision.bound_ctime_ns),
        )
        if _binding_tuple(after) != planned_binding:
            raise ReconciliationError(
                f"{label} changed while being copied: {source}"
            )
        if not _lexists(source) or source.is_symlink():
            raise ReconciliationError(
                f"{label} pathname changed while being copied: {source}"
            )
        current = source.stat()
        if _binding_tuple(current) != planned_binding:
            raise ReconciliationError(
                f"{label} pathname no longer names the planned inode: {source}"
            )
        if str(source.resolve(strict=True)) != str(decision.bound_resolved_path):
            raise ReconciliationError(
                f"{label} resolved target changed while being copied: {source}"
            )
        copied_sha = digest.hexdigest()
        if copied_sha != decision.actual_sha256:
            raise ReconciliationError(
                f"{label} SHA-256 changed while being copied: "
                f"planned={decision.actual_sha256}, copied={copied_sha}"
            )
        return temp_path, copied_sha
    except Exception:
        with suppress(OSError):
            os.close(fd)
        temp_path.unlink(missing_ok=True)
        raise


def _quarantine_copy(
    source: Path,
    destination_root: Path,
    decision: AvailabilityDecision,
) -> tuple[Path, str, os.stat_result, list[dict[str, object]]]:
    if decision.actual_sha256 is None:
        raise ReconciliationError(
            f"quarantine decision lacks a planned SHA-256: {decision.rel_path}"
        )
    current_sha = decision.actual_sha256
    source_identity = (
        int(decision.bound_st_dev),
        int(decision.bound_st_ino),
    )
    destination = (
        destination_root
        / f"{decision.screenshot_id:08d}"
        / f"{source.name}.{current_sha[:12]}.quarantine"
    )
    created_directories = _ensure_directory_chain(
        destination.parent,
        None,
        allow_symlink_ancestor=False,
    )
    succeeded = False
    try:
        if _lexists(destination):
            _verify_decision_binding(decision, label="quarantine source")
            existing = _snapshot_regular_file(
                destination,
                hash_content=True,
                label="quarantine destination",
            )
            if existing["sha256"] != current_sha:
                raise ReconciliationError(
                    f"quarantine collision with different bytes: {destination}"
                )
            if (
                int(existing["st_dev"]),
                int(existing["st_ino"]),
            ) == source_identity:
                raise ReconciliationError(
                    "quarantine destination is not an independent copy: "
                    f"source={source}, destination={destination}"
                )
            succeeded = True
            return (
                destination,
                current_sha,
                destination.stat(),
                created_directories,
            )

        temp_path, copied_sha = _copy_bound_source_to_temp(
            decision,
            destination.parent,
            f".{destination.name}.",
            label="quarantine source",
        )
        try:
            if copied_sha != current_sha:
                raise ReconciliationError(
                    f"quarantine temporary copy verification failed: {temp_path}"
                )
            try:
                os.link(temp_path, destination)
            except FileExistsError as exc:
                existing = _snapshot_regular_file(
                    destination,
                    hash_content=True,
                    label="quarantine destination",
                )
                if existing["sha256"] != current_sha:
                    raise ReconciliationError(
                        "quarantine destination race with different bytes: "
                        f"{destination}"
                    ) from exc
            _fsync_directory(destination.parent)
            destination_stat = destination.stat()
            if _stat_identity(destination_stat) == source_identity:
                raise ReconciliationError(
                    "quarantine destination is not an independent copy: "
                    f"source={source}, destination={destination}"
                )
            succeeded = True
            return (
                destination,
                current_sha,
                destination_stat,
                created_directories,
            )
        finally:
            temp_path.unlink(missing_ok=True)
    finally:
        if not succeeded:
            for entry in reversed(created_directories):
                directory = Path(str(entry["path"]))
                identity = (int(entry["st_dev"]), int(entry["st_ino"]))
                if _lexists(directory) and _same_inode(directory, identity):
                    try:
                        directory.rmdir()
                        _fsync_directory(directory.parent)
                    except OSError as exc:
                        if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                            raise


def _install_restore_no_overwrite(
    decision: AvailabilityDecision,
    *,
    compensation: list[dict[str, object]],
    fault_hook: FaultHook | None,
) -> dict[str, object]:
    operational_path = Path(decision.expected_path)
    resolved_destination = Path(decision.resolved_expected_path)
    candidate = Path(decision.candidate_path or "")
    if _lexists(operational_path) or _lexists(resolved_destination):
        raise ReconciliationError(
            "refusing to overwrite an existing restore destination: "
            f"operational={operational_path}, resolved={resolved_destination}"
        )
    if operational_path.resolve(strict=False) != resolved_destination:
        raise ReconciliationError(
            "restore destination resolved target changed after planning: "
            f"planned={resolved_destination}, "
            f"current={operational_path.resolve(strict=False)}"
        )

    _ensure_directory_chain(
        resolved_destination.parent,
        compensation,
        allow_symlink_ancestor=False,
    )
    temp_path, copied_sha = _copy_bound_source_to_temp(
        decision,
        resolved_destination.parent,
        f".{resolved_destination.name}.restore.",
        label="restore candidate",
    )
    installed_identity: tuple[int, int] | None = None
    try:
        if copied_sha != decision.expected_sha256:
            raise ReconciliationError(
                f"restore temporary copy verification failed: {temp_path}"
            )
        _call_fault_hook(
            fault_hook,
            "before_restore_install",
            {
                "screenshot_id": decision.screenshot_id,
                "expected_path": str(operational_path),
                "resolved_destination": str(resolved_destination),
                "candidate_path": str(candidate),
                "sha256": copied_sha,
            },
        )
        if _lexists(operational_path) or _lexists(resolved_destination):
            raise ReconciliationError(
                "restore destination appeared; no overwrite performed: "
                f"operational={operational_path}, resolved={resolved_destination}"
            )
        if operational_path.resolve(strict=False) != resolved_destination:
            raise ReconciliationError(
                "restore destination resolution changed immediately before "
                "installation: "
                f"operational={operational_path}, resolved={resolved_destination}"
            )
        try:
            os.link(temp_path, resolved_destination)
        except FileExistsError as exc:
            raise ReconciliationError(
                "restore destination appeared; no overwrite performed: "
                f"{resolved_destination}"
            ) from exc
        _fsync_directory(resolved_destination.parent)
        installed = _snapshot_regular_file(
            resolved_destination,
            hash_content=True,
            label="restored source",
        )
        installed_identity = (
            int(installed["st_dev"]),
            int(installed["st_ino"]),
        )
        if installed["sha256"] != decision.expected_sha256:
            raise ReconciliationError(
                f"restored file verification failed: {resolved_destination}"
            )
        try:
            operational_resolved = operational_path.resolve(strict=True)
            operational_identity = _stat_identity(operational_path.stat())
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise ReconciliationError(
                "operational source path did not retain the installed inode: "
                f"operational={operational_path}, "
                f"resolved={resolved_destination}"
            ) from exc
        if (
            operational_resolved != resolved_destination
            or operational_identity != installed_identity
        ):
            raise ReconciliationError(
                "operational source path did not retain the installed inode: "
                f"operational={operational_path}, resolved={resolved_destination}"
            )
        receipt = {
            "action": "restored",
            "source": str(candidate),
            "operational_path": str(operational_path),
            "path": str(resolved_destination),
            "sha256": installed["sha256"],
            "size_bytes": installed["size_bytes"],
            "st_dev": installed["st_dev"],
            "st_ino": installed["st_ino"],
        }
        compensation.append({"kind": "file", **receipt})
        return receipt
    except Exception as exc:
        if (
            installed_identity is not None
            and _same_inode(resolved_destination, installed_identity)
        ):
            current_sha = sha256_file(resolved_destination)
            if current_sha == decision.expected_sha256:
                resolved_destination.unlink()
                _fsync_directory(resolved_destination.parent)
            else:
                raise ReconciliationError(
                    "restore installation failed and local compensation was unsafe: "
                    f"path={resolved_destination}, "
                    f"expected_sha256={decision.expected_sha256}, "
                    f"actual_sha256={current_sha}"
                ) from exc
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def apply_file_actions_atomic(
    decisions: Iterable[AvailabilityDecision],
    *,
    quarantine_dir: Path,
    receipts: list[dict[str, object]],
    compensation: list[dict[str, object]],
    fault_hook: FaultHook | None = None,
) -> None:
    """Apply file actions while preserving ledgers across raised exceptions."""
    for decision in decisions:
        expected = Path(decision.expected_path)
        if decision.action == "restore_exact":
            receipts.append(
                _install_restore_no_overwrite(
                    decision,
                    compensation=compensation,
                    fault_hook=fault_hook,
                )
            )
        elif decision.action in {
            "quarantine_candidate_mismatch",
            "quarantine_existing_mismatch",
        }:
            source = (
                Path(decision.candidate_path or "")
                if decision.action == "quarantine_candidate_mismatch"
                else expected
            )
            destination, current_sha, destination_stat, created_dirs = (
                _quarantine_copy(source, quarantine_dir, decision)
            )
            receipts.append(
                {
                    "action": (
                        "quarantined_candidate_copy"
                        if decision.action == "quarantine_candidate_mismatch"
                        else "quarantined_existing_copy"
                    ),
                    "source": str(source),
                    "path": str(destination),
                    "sha256": current_sha,
                    "size_bytes": destination_stat.st_size,
                    "st_dev": destination_stat.st_dev,
                    "st_ino": destination_stat.st_ino,
                    "created_directories": created_dirs,
                }
            )




def _compensate_restores(
    entries: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Remove only attempt-created files/directories with unchanged identity."""
    ordered = list(entries)
    removed: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for entry in reversed(ordered):
        path = Path(str(entry["path"]))
        kind = str(entry.get("kind", "file"))
        identity = (int(entry["st_dev"]), int(entry["st_ino"]))
        if not _lexists(path):
            removed.append({"path": str(path), "status": "already_absent"})
            continue
        if path.is_symlink() or not _same_inode(path, identity):
            failures.append({"path": str(path), "reason": "inode_changed"})
            continue
        if kind == "directory":
            try:
                path.rmdir()
                _fsync_directory(path.parent)
                removed.append({"path": str(path), "status": "removed_directory"})
            except OSError as exc:
                if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                    removed.append(
                        {
                            "path": str(path),
                            "status": "retained_nonempty_directory",
                        }
                    )
                else:
                    failures.append(
                        {
                            "path": str(path),
                            "reason": f"directory_remove_failed:{exc}",
                        }
                    )
            continue
        expected_sha = str(entry["sha256"])
        current_sha = sha256_file(path)
        if current_sha != expected_sha:
            failures.append(
                {
                    "path": str(path),
                    "reason": "sha256_changed",
                    "expected_sha256": expected_sha,
                    "actual_sha256": current_sha,
                }
            )
            continue
        path.unlink()
        _fsync_directory(path.parent)
        removed.append({"path": str(path), "status": "removed"})
    return {
        "attempted": len(ordered),
        "removed": removed,
        "failures": failures,
        "complete": not failures,
    }



def _verify_artifact_receipt(
    receipt: Mapping[str, object],
    *,
    label: str,
) -> None:
    path = Path(str(receipt["path"]))
    if not path.is_file():
        raise ReconciliationError(
            f"{label} disappeared before database commit: {path}"
        )
    try:
        identity = (int(receipt["st_dev"]), int(receipt["st_ino"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReconciliationError(
            f"{label} receipt lacks a valid inode identity: {path}"
        ) from exc
    if not _same_inode(path, identity):
        raise ReconciliationError(
            f"{label} inode changed before database commit: {path}"
        )
    current_sha = sha256_file(path)
    expected_sha = str(receipt["sha256"])
    if current_sha != expected_sha:
        raise ReconciliationError(
            f"{label} SHA-256 changed before database commit: "
            f"path={path}, expected={expected_sha}, actual={current_sha}"
        )
    if "size_bytes" in receipt:
        current_size = path.stat().st_size
        if current_size != int(receipt["size_bytes"]):
            raise ReconciliationError(
                f"{label} size changed before database commit: "
                f"path={path}, expected={receipt['size_bytes']}, "
                f"actual={current_size}"
            )


def _verify_backup_receipt(receipt: Mapping[str, object]) -> None:
    _verify_artifact_receipt(receipt, label="verified backup")


def _verify_file_receipts(
    receipts: Iterable[Mapping[str, object]],
) -> None:
    labels = {
        "restored": "restored source",
        "quarantined_candidate_copy": "quarantine copy",
        "quarantined_existing_copy": "quarantine copy",
        "report_transitions": "transitions report",
        "report_summary": "summary report",
        "terminal_apply_receipt": "terminal apply receipt",
    }
    for receipt in receipts:
        action = str(receipt.get("action", ""))
        label = labels.get(action)
        if label is None:
            raise ReconciliationError(
                f"unhandled file receipt action before database commit: {action!r}"
            )
        _verify_artifact_receipt(receipt, label=label)



def _verify_filesystem_preconditions(
    decisions: Iterable[AvailabilityDecision],
    receipts: Iterable[Mapping[str, object]],
) -> None:
    """Revalidate every path binding and created artifact before commit."""
    _verify_file_receipts(receipts)
    for decision in decisions:
        expected = Path(decision.expected_path)
        candidate = Path(decision.candidate_path or "")
        current_resolved = str(expected.resolve(strict=False))
        if current_resolved != decision.resolved_expected_path:
            raise ReconciliationError(
                "expected source resolution changed after locked planning: "
                f"path={expected}, planned={decision.resolved_expected_path}, "
                f"current={current_resolved}"
            )
        if decision.action == "restore_exact":
            continue
        if decision.action in {
            "mark_missing",
            "archived_absent",
            "quarantine_candidate_mismatch",
        }:
            if _lexists(expected):
                raise ReconciliationError(
                    f"expected source appeared after locked planning: {expected}"
                )
        elif decision.action == "candidate_missing":
            if _lexists(expected) or _lexists(candidate):
                raise ReconciliationError(
                    "restore candidate or expected source changed after locked "
                    f"planning: expected={expected}, candidate={candidate}"
                )
        elif decision.action in {
            "verified_on_disk",
            "quarantine_existing_mismatch",
            "present_on_disk",
        }:
            _verify_decision_binding(decision, label="expected source")
        elif decision.action != "no_change":
            raise ReconciliationError(
                f"unhandled reconciliation action precondition: {decision.action}"
            )



def _apply_database_updates(
    conn: sqlite3.Connection,
    decisions: list[AvailabilityDecision],
    *,
    git_sha: str | None,
    backup_receipt: Mapping[str, object],
    digest: str,
    operation_timestamp: str,
) -> dict[str, object]:
    """Prepare database mutations; caller finalizes the run before commit."""
    added = migrate_schema(conn)
    stamp = operation_timestamp
    changed = [decision for decision in decisions if decision.changes_database]
    mismatch_count = sum(
        decision.action
        in {
            "quarantine_candidate_mismatch",
            "quarantine_existing_mismatch",
            "candidate_missing",
        }
        for decision in decisions
    )
    cursor = conn.execute(
        """
        INSERT INTO processing_runs
            (run_kind, started_at, status, n_inputs, n_processed,
             n_failed, git_sha, notes)
        VALUES ('source_reconcile', ?, 'in_progress', ?, 0, 0, ?, ?)
        """,
        (
            stamp,
            len(decisions),
            git_sha,
            json.dumps(
                {
                    "protocol": SOURCE_AVAILABILITY_PROTOCOL,
                    "state": "commit_prepared",
                    "schema_columns_added": added,
                    "plan_digest": digest,
                    "backup_sha256": backup_receipt["sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    run_id = int(cursor.lastrowid)

    for decision in changed:
        update = conn.execute(
            """
            UPDATE screenshots
            SET source_availability=?,
                availability_checked_at=?,
                availability_detail=?,
                availability_source=?
            WHERE screenshot_id=?
              AND sha256=?
              AND rel_path=?
              AND source_availability=?
              AND availability_detail IS ?
              AND availability_source IS ?
            """,
            (
                decision.proposed_availability,
                decision.checked_at,
                decision.proposed_detail,
                decision.proposed_source,
                decision.screenshot_id,
                decision.expected_sha256,
                decision.rel_path,
                decision.previous_availability,
                decision.previous_detail,
                decision.previous_source,
            ),
        )
        if update.rowcount != 1:
            raise ReconciliationError(
                "database row changed after locked planning: "
                f"screenshot_id={decision.screenshot_id}"
            )

    return {
        "protocol": SOURCE_AVAILABILITY_PROTOCOL,
        "state": "commit_prepared",
        "run_id": run_id,
        "operation_timestamp": stamp,
        "schema_columns_added": added,
        "database_updates": len(changed),
        "mismatches": mismatch_count,
        "plan_digest": digest,
        "backup_sha256": backup_receipt["sha256"],
    }


def _finalize_processing_run(
    conn: sqlite3.Connection,
    apply_receipt: Mapping[str, object],
    terminal_receipt: Mapping[str, object],
) -> None:
    update = conn.execute(
        """
        UPDATE processing_runs
        SET ended_at=?, status='completed', n_processed=?, n_failed=?, notes=?
        WHERE run_id=? AND status='in_progress'
        """,
        (
            apply_receipt["operation_timestamp"],
            apply_receipt["database_updates"],
            apply_receipt["mismatches"],
            json.dumps(terminal_receipt, sort_keys=True, separators=(",", ":")),
            apply_receipt["run_id"],
        ),
    )
    if update.rowcount != 1:
        raise ReconciliationError(
            f"processing run could not be finalized: {apply_receipt['run_id']}"
        )



def _load_authoritative_committed_receipt(
    db_path: Path,
    *,
    run_id: int,
    receipt_sha256: str,
) -> dict[str, object] | None:
    """Resolve an ambiguous commit by reading the authoritative run row."""
    try:
        conn = connect_read_only(db_path)
        try:
            row = conn.execute(
                "SELECT status, notes FROM processing_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
    except (OSError, sqlite3.Error, ReconciliationError):
        return None
    if row is None or str(row[0]) != "completed":
        return None
    try:
        receipt = json.loads(str(row[1]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(receipt, dict):
        return None
    if receipt.get("protocol") != SOURCE_AVAILABILITY_PROTOCOL:
        return None
    if receipt.get("state") != "committed":
        return None
    if receipt.get("receipt_sha256") != receipt_sha256:
        return None
    if _receipt_sha256(receipt) != receipt_sha256:
        return None
    return receipt


def _commit_connection(conn: sqlite3.Connection) -> None:
    """Dedicated seam for commit-outcome fault injection."""
    conn.commit()


def reconcile_apply(
    db_path: Path,
    repo_root: Path,
    *,
    backup_path: Path | None,
    quarantine_dir: Path,
    verify_sha: bool = False,
    restore_entries: Mapping[str, RestoreEntry] | None = None,
    checked_at: str | None = None,
    expected_plan_digest: str | None = None,
    expected_snapshot_sha256: str | None = None,
    git_sha: str | None = None,
    report_output_dir: Path | None = None,
    restore_manifest_path: Path | None = None,
    expected_restore_manifest_receipt: Mapping[str, object] | None = None,
    migration_required: bool = False,
    fault_hook: FaultHook | None = None,
) -> tuple[
    list[AvailabilityDecision],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
]:
    """Execute the final locked, backed-up, compensating state machine."""
    if backup_path is None:
        raise ReconciliationError("apply requires a verified backup destination")

    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    backup_path = backup_path.expanduser()
    quarantine_dir = quarantine_dir.expanduser()
    report_output_dir = (
        report_output_dir.expanduser() if report_output_dir is not None else None
    )
    stamp = checked_at or utc_now()
    restore_entries = restore_entries or {}
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    compensation_entries: list[dict[str, object]] = []
    source_file_receipts: list[dict[str, object]] = []
    report_receipts: list[dict[str, object]] = []
    backup_receipt: dict[str, object] | None = None
    restore_manifest_receipt: dict[str, object] | None = None
    committed = False
    prepared_return: tuple[
        list[AvailabilityDecision],
        dict[str, object],
        dict[str, object],
        list[dict[str, object]],
    ] | None = None
    phase = "initializing"
    final_digest: str | None = None
    apply_receipt: dict[str, object] | None = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        phase = "lock_acquired"
        locked_snapshot_sha256 = connection_snapshot_sha256(conn)
        if (
            expected_snapshot_sha256 is not None
            and locked_snapshot_sha256 != expected_snapshot_sha256
        ):
            raise ReconciliationError(
                "database snapshot changed before locked apply: "
                f"expected={expected_snapshot_sha256}, "
                f"final={locked_snapshot_sha256}"
            )
        if restore_manifest_path is not None:
            restore_manifest_receipt = _verify_restore_manifest_binding(
                restore_manifest_path,
                restore_entries,
                expected_restore_manifest_receipt,
            )
        elif expected_restore_manifest_receipt is not None:
            raise ReconciliationError(
                "restore manifest receipt supplied without restore manifest path"
            )
        final_decisions = plan_reconciliation(
            conn,
            repo_root,
            verify_sha=verify_sha,
            restore_entries=restore_entries,
            checked_at=stamp,
        )
        final_digest = plan_digest(final_decisions)
        if expected_plan_digest is not None and final_digest != expected_plan_digest:
            raise ReconciliationError(
                "reconciliation plan became stale before locked apply: "
                f"expected={expected_plan_digest}, final={final_digest}"
            )
        phase = "final_plan_bound"
        validate_apply_control_paths(
            db_path,
            backup_path,
            quarantine_dir,
            final_decisions,
        )
        if report_output_dir is not None:
            validate_report_output_paths(
                report_output_dir,
                final_decisions,
                db_path=db_path,
                backup_path=backup_path,
                quarantine_dir=quarantine_dir,
                restore_manifest_path=restore_manifest_path,
            )
        phase = "control_paths_validated"
        _call_fault_hook(
            fault_hook,
            "after_final_plan",
            {
                "plan_digest": final_digest,
                "rows": len(final_decisions),
                "database_snapshot_sha256": locked_snapshot_sha256,
            },
        )

        backup_receipt = backup_database_locked(
            conn,
            db_path,
            backup_path,
            fault_hook=fault_hook,
        )
        phase = "backup_verified"
        _call_fault_hook(
            fault_hook,
            "after_backup_verified",
            {"backup": backup_receipt},
        )
        apply_file_actions_atomic(
            final_decisions,
            quarantine_dir=quarantine_dir,
            receipts=source_file_receipts,
            compensation=compensation_entries,
            fault_hook=fault_hook,
        )
        phase = "file_actions_installed"
        _call_fault_hook(
            fault_hook,
            "after_file_actions",
            {"file_receipts": source_file_receipts},
        )
        _verify_backup_receipt(backup_receipt)
        _verify_filesystem_preconditions(
            final_decisions,
            source_file_receipts,
        )
        phase = "file_actions_verified"
        _call_fault_hook(
            fault_hook,
            "after_file_actions_verified",
            {"file_receipts": source_file_receipts},
        )
        apply_receipt = _apply_database_updates(
            conn,
            final_decisions,
            git_sha=git_sha,
            backup_receipt=backup_receipt,
            digest=final_digest,
            operation_timestamp=stamp,
        )
        phase = "database_updates_prepared"
        _call_fault_hook(
            fault_hook,
            "after_database_updates_prepared",
            {"apply_receipt": apply_receipt},
        )
        terminal_receipt: dict[str, object] = {
            **apply_receipt,
            "phase_history": _phase_history_through(
                "database_updates_prepared"
            ),
            "database_snapshot_sha256_before": locked_snapshot_sha256,
            "backup": dict(backup_receipt),
            "restore_manifest": (
                dict(restore_manifest_receipt)
                if restore_manifest_receipt is not None
                else None
            ),
            "restore_entries_digest": _restore_entries_digest(restore_entries),
            "source_file_receipts": sorted(
                source_file_receipts,
                key=lambda item: (
                    str(item.get("action", "")),
                    str(item.get("path", "")),
                ),
            ),
            "compensation_policy": {
                "restored_and_report_artifacts": "remove_if_same_inode_and_sha",
                "backup_and_quarantine": "retain_as_evidence",
            },
        }
        summary = summarize(
            final_decisions,
            mode="apply",
            migration_required=migration_required,
            backup=backup_receipt,
            file_receipts=source_file_receipts,
        )
        summary.update(
            {
                "db_path": str(db_path),
                "repo_root": str(repo_root),
                "quarantine_dir": str(quarantine_dir),
                "restore_manifest_path": (
                    str(restore_manifest_path)
                    if restore_manifest_path is not None
                    else None
                ),
                "restore_manifest_receipt": restore_manifest_receipt,
                "restore_entries_digest": _restore_entries_digest(restore_entries),
                "database_snapshot_sha256_before": locked_snapshot_sha256,
                "apply_receipt": apply_receipt,
            }
        )
        if report_output_dir is not None:
            generation_dir, report_receipts, terminal_receipt = _publish_apply_reports(
                report_output_dir,
                final_decisions,
                summary,
                terminal_receipt,
                run_id=int(apply_receipt["run_id"]),
                plan_digest_value=final_digest,
                db_path=db_path,
                backup_path=backup_path,
                quarantine_dir=quarantine_dir,
                restore_manifest_path=restore_manifest_path,
                compensation=compensation_entries,
            )
            terminal_receipt["report_generation_dir"] = str(generation_dir)
        terminal_receipt["report_receipts"] = report_receipts
        phase = "reports_prepared"
        _call_fault_hook(
            fault_hook,
            "after_reports_prepared",
            {"report_receipts": report_receipts},
        )

        committed_terminal_receipt = {
            **terminal_receipt,
            "state": "committed",
            "phase_history": _phase_history_through("committed"),
            "report_receipts": report_receipts,
        }
        committed_terminal_receipt["receipt_sha256"] = _receipt_sha256(
            committed_terminal_receipt
        )
        apply_receipt["report_receipts"] = report_receipts
        apply_receipt["terminal_receipt"] = committed_terminal_receipt
        _finalize_processing_run(
            conn,
            apply_receipt,
            committed_terminal_receipt,
        )
        phase = "processing_run_finalized"
        _call_fault_hook(
            fault_hook,
            "after_processing_run_finalized",
            {"apply_receipt": apply_receipt},
        )

        _call_fault_hook(
            fault_hook,
            "before_database_commit",
            {"apply_receipt": apply_receipt},
        )
        _verify_backup_receipt(backup_receipt)
        _verify_filesystem_preconditions(
            final_decisions,
            [*source_file_receipts, *report_receipts],
        )
        phase = "precommit_verified"
        ordered_sources = sorted(
            source_file_receipts,
            key=lambda item: (
                str(item.get("action", "")),
                str(item.get("path", "")),
            ),
        )
        apply_receipt["compensation"] = {
            "armed": len(compensation_entries),
            "attempted": 0,
            "removed": [],
            "failures": [],
            "complete": True,
        }
        prepared_return = (
            final_decisions,
            backup_receipt,
            apply_receipt,
            ordered_sources,
        )
        try:
            _commit_connection(conn)
            commit_outcome = "direct"
        except Exception as commit_exc:
            if conn.in_transaction:
                raise
            authoritative = _load_authoritative_committed_receipt(
                db_path,
                run_id=int(apply_receipt["run_id"]),
                receipt_sha256=str(
                    committed_terminal_receipt["receipt_sha256"]
                ),
            )
            if authoritative is None:
                raise ReconciliationError(
                    "database commit outcome could not be verified after an "
                    f"exception: {type(commit_exc).__name__}: {commit_exc}"
                ) from commit_exc
            committed = True
            apply_receipt["terminal_receipt"] = authoritative
            _verify_backup_receipt(backup_receipt)
            _verify_filesystem_preconditions(
                final_decisions,
                [*source_file_receipts, *report_receipts],
            )
            commit_outcome = "resolved_after_commit_exception"
        committed = True
        phase = "committed"
        apply_receipt["state"] = "committed"
        apply_receipt["commit_outcome"] = commit_outcome
        return prepared_return
    except Exception as exc:
        if committed:
            raise ReconciliationError(
                "database commit completed but a post-commit error occurred; "
                f"run receipt must be inspected: {type(exc).__name__}: {exc}"
            ) from exc
        if conn.in_transaction:
            conn.rollback()
        compensation = _compensate_restores(compensation_entries)
        failure_receipt: dict[str, object] = {
            "protocol": SOURCE_AVAILABILITY_PROTOCOL,
            "state": (
                "rollback_incomplete"
                if not compensation["complete"]
                else "rolled_back"
            ),
            "failed_phase": phase,
            "phase_history": (
                _phase_history_through(phase)
                if phase in RECONCILIATION_PHASES
                else []
            ),
            "cause_type": type(exc).__name__,
            "cause": str(exc),
            "plan_digest": final_digest,
            "backup": dict(backup_receipt) if backup_receipt else None,
            "restore_manifest": restore_manifest_receipt,
            "restore_entries_digest": _restore_entries_digest(restore_entries),
            "source_file_receipts": source_file_receipts,
            "report_receipts": report_receipts,
            "compensation": compensation,
        }
        failure_receipt["receipt_sha256"] = _receipt_sha256(failure_receipt)
        if not compensation["complete"]:
            raise ReconciliationError(
                "atomic reconciliation failed and compensation was incomplete: "
                f"cause={type(exc).__name__}: {exc}; compensation={compensation}",
                receipt=failure_receipt,
            ) from exc
        message = (
            str(exc)
            if isinstance(exc, ReconciliationError)
            else (
                f"atomic reconciliation failed: {type(exc).__name__}: {exc}; "
                f"compensation={compensation}"
            )
        )
        raise ReconciliationError(
            message,
            receipt=failure_receipt,
        ) from exc
    finally:
        conn.close()



def apply_reconciliation(*args: Any, **kwargs: Any) -> None:
    """Fail closed for the retired preplanned, backup-unbound apply API."""
    del args, kwargs
    raise ReconciliationError(
        "preplanned apply is disabled; use reconcile_apply() with backup_path"
    )


def database_snapshot_sha256(db_path: Path) -> str:
    conn = connect_read_only(db_path)
    try:
        return connection_snapshot_sha256(conn)
    finally:
        conn.close()


def summarize(
    decisions: Iterable[AvailabilityDecision],
    *,
    mode: str,
    migration_required: bool,
    backup: Mapping[str, object] | None = None,
    file_receipts: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    ordered = list(decisions)
    by_previous: dict[str, int] = {}
    by_proposed: dict[str, int] = {}
    by_action: dict[str, int] = {}
    transitions = 0
    database_updates = 0
    for decision in ordered:
        by_previous[decision.previous_availability] = (
            by_previous.get(decision.previous_availability, 0) + 1
        )
        by_proposed[decision.proposed_availability] = (
            by_proposed.get(decision.proposed_availability, 0) + 1
        )
        by_action[decision.action] = by_action.get(decision.action, 0) + 1
        transitions += int(
            decision.previous_availability != decision.proposed_availability
        )
        database_updates += int(decision.changes_database)

    return {
        "protocol": SOURCE_AVAILABILITY_PROTOCOL,
        "mode": mode,
        "migration_required": migration_required,
        "rows_examined": len(ordered),
        "availability_transitions": transitions,
        "database_updates": database_updates,
        "plan_digest": plan_digest(ordered),
        "by_previous": dict(sorted(by_previous.items())),
        "by_proposed": dict(sorted(by_proposed.items())),
        "by_action": dict(sorted(by_action.items())),
        "backup": dict(backup) if backup is not None else None,
        "file_receipts": sorted(
            (dict(receipt) for receipt in file_receipts),
            key=lambda item: (str(item.get("action", "")), str(item.get("path", ""))),
        ),
    }


REPORT_FIELDS = [
    "screenshot_id",
    "rel_path",
    "expected_sha256",
    "previous_availability",
    "proposed_availability",
    "previous_detail",
    "proposed_detail",
    "previous_source",
    "proposed_source",
    "action",
    "expected_path",
    "resolved_expected_path",
    "candidate_path",
    "actual_sha256",
    "bound_path",
    "bound_resolved_path",
    "bound_size_bytes",
    "bound_st_dev",
    "bound_st_ino",
    "bound_mtime_ns",
    "bound_ctime_ns",
    "checked_at",
]


def write_reports(
    output_dir: Path,
    decisions: Iterable[AvailabilityDecision],
    summary: Mapping[str, object],
) -> tuple[Path, Path]:
    """Publish immutable, content-addressed dry-run reports."""
    ordered = sorted(decisions, key=lambda item: item.screenshot_id)
    backup = summary.get("backup")
    backup_path = (
        Path(str(backup["path"]))
        if isinstance(backup, Mapping) and backup.get("path")
        else None
    )
    db_value = summary.get("db_path")
    quarantine_value = summary.get("quarantine_dir")
    manifest_value = summary.get("restore_manifest_path")
    # ``checked_at`` records invocation time, not plan identity. Excluding it
    # keeps unchanged public dry runs byte-identical and safely idempotent.
    csv_payload = _csv_report_bytes(ordered, include_checked_at=False)
    json_payload = _json_report_bytes(summary)
    content_digest = hashlib.sha256(
        csv_payload + b"\x00" + json_payload
    ).hexdigest()
    generation_dir = (
        output_dir
        / "dry-runs"
        / f"dry-run-{content_digest[:24]}"
    )
    validate_report_output_paths(
        output_dir,
        ordered,
        db_path=Path(str(db_value)) if db_value else None,
        backup_path=backup_path,
        quarantine_dir=(Path(str(quarantine_value)) if quarantine_value else None),
        restore_manifest_path=(
            Path(str(manifest_value)) if manifest_value else None
        ),
        generation_dir=generation_dir,
        allow_existing_report_files=True,
    )
    csv_path = generation_dir / REPORT_FILENAMES[0]
    json_path = generation_dir / REPORT_FILENAMES[1]
    if _lexists(generation_dir):
        if not generation_dir.is_dir() or generation_dir.is_symlink():
            raise ReconciliationError(
                "dry-run report generation path is not a directory: "
                f"{generation_dir}"
            )
        expected = {
            csv_path: hashlib.sha256(csv_payload).hexdigest(),
            json_path: hashlib.sha256(json_payload).hexdigest(),
        }
        actual_names = {item.name for item in generation_dir.iterdir()}
        if actual_names != {path.name for path in expected}:
            raise ReconciliationError(
                "existing dry-run report generation has unexpected contents: "
                f"{generation_dir}"
            )
        for path, digest in expected.items():
            if not path.is_file() or path.is_symlink():
                raise ReconciliationError(
                    f"existing dry-run report is not a regular file: {path}"
                )
            if sha256_file(path) != digest:
                raise ReconciliationError(
                    f"existing dry-run report bytes differ: {path}"
                )
        return csv_path, json_path

    compensation: list[dict[str, object]] = []
    try:
        _ensure_directory_chain(
            generation_dir.parent,
            compensation,
            allow_symlink_ancestor=False,
        )
        generation_dir.mkdir()
        info = generation_dir.stat()
        compensation.append(
            {
                "kind": "directory",
                "path": str(generation_dir),
                "st_dev": info.st_dev,
                "st_ino": info.st_ino,
            }
        )
        _fsync_directory(generation_dir.parent)
        _install_bytes_no_overwrite(
            csv_path,
            csv_payload,
            action="report_transitions",
            compensation=compensation,
        )
        _install_bytes_no_overwrite(
            json_path,
            json_payload,
            action="report_summary",
            compensation=compensation,
        )
        return csv_path, json_path
    except Exception as exc:
        compensation_receipt = _compensate_restores(compensation)
        if not compensation_receipt["complete"]:
            raise ReconciliationError(
                "dry-run report publication failed and compensation was "
                f"incomplete: cause={type(exc).__name__}: {exc}; "
                f"compensation={compensation_receipt}"
            ) from exc
        if isinstance(exc, ReconciliationError):
            raise
        raise ReconciliationError(
            "dry-run report publication failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
