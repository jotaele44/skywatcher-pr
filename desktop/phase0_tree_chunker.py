"""Split the validated Phase 0 tree ledger into connector-sized chunks.

Temporary executor-branch utility only. It never updates PR #110 or main.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


EXECUTOR_BRANCH = "codex/phase0-sync-executor-v2"
CHUNK_SIZE = 25
EXPECTED_FEATURE = "1bfaea7c37ff42d0614934b0553cf8aacad9bfcc"
EXPECTED_MAIN = "9cdf63d584bc58495c32a573dc0fc9ddad981ab8"
EXPECTED_COUNT = 251


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


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


def split_and_publish_tree_ledger(repo_root: Path) -> Path:
    ledger_path = repo_root / "executor-output" / "phase0_merge_publish_receipt.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger["feature_parent"] != EXPECTED_FEATURE:
        raise RuntimeError("unexpected feature parent")
    if ledger["main_parent"] != EXPECTED_MAIN:
        raise RuntimeError("unexpected main parent")
    if ledger["remote_head"] != EXPECTED_FEATURE:
        raise RuntimeError("feature ref moved before chunk publication")
    if ledger["frontend_delta"] or ledger["data_delta"]:
        raise RuntimeError("scope delta present in validated ledger")
    if not ledger["ruff_clean"]:
        raise RuntimeError("validated ledger is not Ruff-clean")
    elements = ledger["tree_elements"]
    if len(elements) != EXPECTED_COUNT or ledger["tree_element_count"] != EXPECTED_COUNT:
        raise RuntimeError("unexpected tree element count")

    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / "tree-chunks"
        staged.mkdir(parents=True)
        chunks = []
        for index in range(0, len(elements), CHUNK_SIZE):
            rows = elements[index : index + CHUNK_SIZE]
            name = f"chunk-{index // CHUNK_SIZE:02d}.json"
            (staged / name).write_text(
                json.dumps(rows, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            chunks.append({"file": name, "count": len(rows)})

        manifest = {
            "base_tree_sha": ledger["base_tree_sha"],
            "validated_tree_sha": ledger["validated_tree_sha"],
            "feature_parent": ledger["feature_parent"],
            "main_parent": ledger["main_parent"],
            "tree_element_count": len(elements),
            "chunk_size": CHUNK_SIZE,
            "chunks": chunks,
            "changed_file_count": ledger["changed_file_count"],
            "conflicts": ledger["conflicts"],
            "frontend_delta": ledger["frontend_delta"],
            "data_delta": ledger["data_delta"],
            "ruff_clean": ledger["ruff_clean"],
            "push_force": False,
        }
        (staged / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        _run("git", "fetch", "origin", EXECUTOR_BRANCH, cwd=repo_root)
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
            destination = worktree / "executor-output" / "tree-chunks"
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(staged, destination)
            _run("git", "config", "user.name", "phase0-tree-chunker", cwd=worktree)
            _run(
                "git",
                "config",
                "user.email",
                "actions@users.noreply.github.com",
                cwd=worktree,
            )
            _run("git", "add", "executor-output/tree-chunks", cwd=worktree)
            _run(
                "git",
                "commit",
                "-m",
                "Publish validated Phase 0 tree chunks",
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

        summary = repo_root / "phase0_tree_chunk_manifest.json"
        summary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary
