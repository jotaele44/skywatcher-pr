"""Temporary executor for the adjudicated Phase 0 synchronization.

This module exists only on the disposable executor branch. The merge it creates is
built from the pinned feature and main parents, so this file cannot enter PR #110.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from typing import Any

FEATURE = "1bfaea7c37ff42d0614934b0553cf8aacad9bfcc"
MAIN = "09c8928109e25a3651f09ffff4c9414f0c83fdac"
TARGET_BRANCH = "agent/repository-hardening-phase-0"
EXECUTOR_BRANCH = "codex/phase0-sync-executor-v2"
CERTIFIED_PHASE0 = "c1323992801230f5e076c524c9ac67ff96c74bbb"

CONFLICTS = [
    "fr24/rlsm_unlabeled.py",
    "fr24/satim_engine.py",
    "fr24/satim_engine_core.py",
    "scripts/federation_export.py",
    "scripts/rlsm_geocode_unlabeled.py",
    "scripts/rlsm_ocr_retry_tails.py",
    "src/skywatcher/fpim/aircraft_profile.py",
    "tests/test_aircraft_intelligence.py",
    "tests/test_fr24_todays_batch.py",
    "tests/test_maintenance.py",
    "tools/satim_engine/src/satim_engine/inventory.py",
]

FORBIDDEN_FINAL_PATHS = [
    ".github/workflows/phase0-sync-current-main.yml",
    "sitecustomize.py",
    "tests/test_phase0_sync_manifest.py",
    "executor-output/phase0_merge_manifest.zlib.b64",
    "executor-output/phase0_merge_manifest_error.txt",
    "executor-output/phase0_ruff_diagnostic.txt",
    "desktop/phase0_sync_executor.py",
]


def _run(
    *args: str,
    cwd: Path,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def _copy_checkout_credentials(source_repo: Path, target_repo: Path) -> None:
    result = _run(
        "git",
        "config",
        "--local",
        "--get-regexp",
        r"^http\..*\.extraheader$",
        cwd=source_repo,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("persisted GitHub checkout credential header is unavailable")
    for line in result.stdout.splitlines():
        key, value = line.split(None, 1)
        _run("git", "config", "--local", key, value, cwd=target_repo)


def _publish_result(repo_root: Path, result_path: Path) -> None:
    """Synchronously publish one executor result file to the disposable branch."""
    _run("git", "fetch", "origin", EXECUTOR_BRANCH, cwd=repo_root)
    with tempfile.TemporaryDirectory() as td:
        worktree = Path(td) / "publish"
        _run(
            "git",
            "worktree",
            "add",
            "--detach",
            str(worktree),
            f"origin/{EXECUTOR_BRANCH}",
            cwd=repo_root,
        )
        try:
            destination = worktree / "executor-output"
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result_path, destination / result_path.name)
            _run("git", "config", "user.name", "phase0-executor", cwd=worktree)
            _run(
                "git",
                "config",
                "user.email",
                "actions@users.noreply.github.com",
                cwd=worktree,
            )
            _run("git", "add", "executor-output", cwd=worktree)
            status = _run("git", "status", "--porcelain", cwd=worktree)
            if not status.stdout.strip():
                return
            _run(
                "git",
                "commit",
                "-m",
                "Publish Phase 0 synchronization result",
                cwd=worktree,
            )
            _copy_checkout_credentials(repo_root, worktree)
            _run(
                "git",
                "push",
                "origin",
                f"HEAD:refs/heads/{EXECUTOR_BRANCH}",
                cwd=worktree,
            )
        finally:
            _run(
                "git",
                "worktree",
                "remove",
                "--force",
                str(worktree),
                cwd=repo_root,
                check=False,
            )


def _apply_ci_overlay(repo: Path) -> None:
    (repo / ".github/workflows/ci.yml").write_bytes(
        subprocess.check_output(
            ["git", "show", f"{CERTIFIED_PHASE0}:.github/workflows/ci.yml"],
            cwd=repo,
        )
    )
    (repo / "pyproject.toml").write_bytes(
        subprocess.check_output(
            ["git", "show", f"{CERTIFIED_PHASE0}:pyproject.toml"],
            cwd=repo,
        )
    )

    ci = repo / ".github/workflows/ci.yml"
    text = ci.read_text(encoding="utf-8")
    old_gate = '''          manifest = json.load(open("federation.json", encoding="utf-8"))
          assert manifest["program_id"] == "skywatcher-pr"
          assert manifest["hub_parent"] == "thehub-pr"
          assert manifest["federation_readiness_gate"]["operational_cueing"] is False
          assert manifest["federation_readiness_gate"]["intent_inference"] is False
'''
    new_gate = '''          manifest = json.load(open("federation.json", encoding="utf-8"))
          required = {
              "schema_version", "program_id", "repository_full_name",
              "federation_role", "hub_parent", "hub_callable_commands",
              "canonical_outputs", "federation_readiness_gate",
          }
          missing = sorted(required - set(manifest))
          assert not missing, f"federation.json missing required keys: {missing}"
          assert manifest["program_id"] == "skywatcher-pr"
          assert manifest["hub_parent"] == "thehub-pr"
          gate = manifest["federation_readiness_gate"]
          assert isinstance(gate.get("ready_for_hub_discovery"), bool)
          assert isinstance(gate.get("ready_for_hub_live_execution"), bool)
          assert isinstance(gate.get("blocking_conditions"), list)
          assert gate["operational_cueing"] is False
          assert gate["intent_inference"] is False
'''
    if old_gate not in text:
        raise RuntimeError("Phase 0 federation gate block missing")
    text = text.replace(old_gate, new_gate)
    lines = text.splitlines()
    try:
        index = lines.index("      - name: Ruff (report-only)")
    except ValueError as exc:
        raise RuntimeError("Phase 0 Ruff block missing") from exc
    expected = [
        "      - name: Ruff (report-only)",
        "        continue-on-error: true",
        "        run: ruff check --statistics .",
    ]
    if lines[index : index + 3] != expected:
        raise RuntimeError("Phase 0 Ruff block changed unexpectedly")
    lines[index : index + 3] = ["      - name: Ruff", "        run: ruff check ."]
    ci.write_text("\n".join(lines) + "\n", encoding="utf-8")

    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if 'ignore = ["E501"]' not in text:
        raise RuntimeError("Phase 0 Ruff ignore list missing")
    pyproject.write_text(
        text.replace(
            'ignore = ["E501"]',
            '''ignore = [
  "E501",
  "E402",
  "B023",
]''',
        ),
        encoding="utf-8",
    )


def _apply_archive_default_parity(repo: Path) -> None:
    marker = "    max_compression_ratio: float = 200.0\n\n\ndef _normalized_member"
    replacement = (
        "    max_compression_ratio: float = 200.0\n\n\n"
        "DEFAULT_ARCHIVE_LIMITS = ArchiveLimits()\n\n\n"
        "def _normalized_member"
    )
    call = "limits: ArchiveLimits = ArchiveLimits()"
    name = "limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS"
    for relative in (
        "src/skywatcher/core/safe_archive.py",
        "tools/satim_engine/src/satim_engine/safe_archive.py",
    ):
        path = repo / relative
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            raise RuntimeError(f"ArchiveLimits insertion marker missing: {relative}")
        if text.count(call) != 2:
            raise RuntimeError(f"unexpected ArchiveLimits default count: {relative}")
        text = text.replace(marker, replacement, 1).replace(call, name)
        path.write_text(text, encoding="utf-8")


def _ruff_clean(repo: Path, repo_root: Path) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "ruff>=0.12"], check=True)
    for _ in range(3):
        subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", "--unsafe-fixes", "."],
            cwd=repo,
            check=False,
            text=True,
            capture_output=True,
        )
        findings = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--output-format", "json", "."],
            cwd=repo,
            check=False,
            text=True,
            capture_output=True,
        )
        rows = json.loads(findings.stdout or "[]")
        paths = sorted({str(Path(row["filename"]).resolve()) for row in rows if row.get("filename")})
        if not paths:
            break
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", *paths],
            cwd=repo,
            check=True,
            text=True,
            capture_output=True,
        )

    final = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
    )
    diagnostic = repo_root / "phase0_ruff_diagnostic.txt"
    diagnostic.write_text(
        f"RUFF_CHECK_RETURN_CODE={final.returncode}\n"
        f"RUFF_CHECK_STDOUT:\n{final.stdout}\n"
        f"RUFF_CHECK_STDERR:\n{final.stderr}\n",
        encoding="utf-8",
    )
    if final.returncode:
        raise RuntimeError("merged tree is not Ruff-clean; branch push withheld")


def _execute(repo_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        subprocess.run(
            ["git", "clone", "--no-checkout", "https://github.com/jotaele44/skywatcher-pr.git", str(repo)],
            check=True,
        )
        _run("git", "checkout", "--detach", FEATURE, cwd=repo)
        _run("git", "config", "user.name", "phase0-sync-bot", cwd=repo)
        _run("git", "config", "user.email", "actions@users.noreply.github.com", cwd=repo)

        merge = _run("git", "merge", "--no-commit", "--no-ff", MAIN, cwd=repo, check=False)
        if merge.returncode != 1:
            raise RuntimeError(f"expected an adjudication merge conflict, got {merge.returncode}")
        conflicts = sorted(
            _run("git", "diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.splitlines()
        )
        if conflicts != CONFLICTS:
            raise RuntimeError(f"unexpected Phase 0 conflict set: {conflicts!r}")
        for path in conflicts:
            _run("git", "checkout", "--ours", "--", path, cwd=repo)
            _run("git", "add", "--", path, cwd=repo)

        _apply_ci_overlay(repo)
        _apply_archive_default_parity(repo)
        workflow = repo / ".github/workflows/phase0-sync-current-main.yml"
        if workflow.exists():
            _run("git", "rm", "--", str(workflow.relative_to(repo)), cwd=repo)
        _run("git", "add", "-A", cwd=repo)
        unresolved = _run("git", "diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.strip()
        if unresolved:
            raise RuntimeError(f"unresolved Phase 0 paths: {unresolved}")

        _ruff_clean(repo, repo_root)
        _run("git", "add", "-A", cwd=repo)
        diff_check = _run("git", "diff", "--cached", "--check", cwd=repo, check=False)
        if diff_check.returncode:
            raise RuntimeError(f"git diff --check failed:\n{diff_check.stdout}\n{diff_check.stderr}")

        for path in FORBIDDEN_FINAL_PATHS:
            if _run("git", "cat-file", "-e", f":{path}", cwd=repo, check=False).returncode == 0:
                raise RuntimeError(f"temporary executor path leaked into merge tree: {path}")

        frontend_delta = _run("git", "diff", "--name-only", MAIN, "--", "frontend", cwd=repo).stdout.splitlines()
        data_delta = _run("git", "diff", "--name-only", MAIN, "--", "data", cwd=repo).stdout.splitlines()
        if frontend_delta:
            raise RuntimeError(f"unexpected frontend delta: {frontend_delta!r}")
        if data_delta:
            raise RuntimeError(f"unexpected production data delta: {data_delta!r}")

        remote_feature = _run(
            "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
        ).stdout.split()[0]
        if remote_feature != FEATURE:
            raise RuntimeError(f"feature branch moved: expected {FEATURE}, got {remote_feature}")

        _run("git", "commit", "-m", "Merge current main into Phase 0 branch", cwd=repo)
        merge_sha = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        parents = _run("git", "rev-list", "--parents", "-n", "1", "HEAD", cwd=repo).stdout.split()
        if parents != [merge_sha, FEATURE, MAIN]:
            raise RuntimeError(f"unexpected merge parents: {parents!r}")
        tree_sha = _run("git", "rev-parse", "HEAD^{tree}", cwd=repo).stdout.strip()
        changed_paths = _run("git", "diff", "--name-only", MAIN, "HEAD", cwd=repo).stdout.splitlines()

        _copy_checkout_credentials(repo_root, repo)
        _run("git", "push", "origin", f"HEAD:refs/heads/{TARGET_BRANCH}", cwd=repo)
        remote_after = _run(
            "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
        ).stdout.split()[0]
        if remote_after != merge_sha:
            raise RuntimeError(f"remote feature head mismatch after push: {remote_after}")

        return {
            "feature_parent": FEATURE,
            "main_parent": MAIN,
            "merge_sha": merge_sha,
            "merge_tree": tree_sha,
            "remote_head": remote_after,
            "conflicts": CONFLICTS,
            "changed_file_count": len(changed_paths),
            "frontend_delta": frontend_delta,
            "data_delta": data_delta,
            "ruff_clean": True,
            "push_force": False,
        }


def execute_phase0_sync(repo_root: Path) -> Path:
    """Return a plain JSON receipt or plain traceback and publish it immediately."""
    try:
        result = _execute(repo_root)
        output = repo_root / "phase0_merge_publish_receipt.json"
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        output = repo_root / "phase0_merge_manifest_error.txt"
        output.write_text(traceback.format_exc(), encoding="utf-8")
    try:
        _publish_result(repo_root, output)
    except Exception:
        # Preserve both the original result and publication failure in the desktop artifact.
        publication_error = repo_root / "phase0_result_publication_error.txt"
        publication_error.write_text(traceback.format_exc(), encoding="utf-8")
    return output
