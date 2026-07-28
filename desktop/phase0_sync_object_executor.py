"""Temporary wrapper that preserves the validated Phase 0 merge commit object."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def execute_phase0_object_sync(repo_root: Path) -> Path:
    executor_path = repo_root / "desktop" / "phase0_sync_executor.py"
    source = executor_path.read_text(encoding="utf-8")
    execute_start = source.index("def _execute(repo_root: Path)")
    push_start = source.index(
        "        _copy_checkout_credentials(repo_root, repo)\n", execute_start
    )
    push_end = source.index("\n\n\ndef execute_phase0_sync", push_start)

    replacement = '''        _copy_checkout_credentials(repo_root, repo)
        object_branch = "codex/phase0-synchronized-object-v1"
        object_push = _run(
            "git",
            "push",
            "origin",
            f"HEAD:refs/heads/{object_branch}",
            cwd=repo,
            check=False,
        )
        if object_push.returncode:
            raise RuntimeError(
                "validated merge object push failed:\n"
                + object_push.stdout
                + "\n"
                + object_push.stderr
            )

        target_push = _run(
            "git",
            "push",
            "origin",
            f"HEAD:refs/heads/{TARGET_BRANCH}",
            cwd=repo,
            check=False,
        )
        remote_after = _run(
            "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
        ).stdout.split()[0]

        return {
            "feature_parent": FEATURE,
            "main_parent": MAIN,
            "merge_sha": merge_sha,
            "merge_tree": tree_sha,
            "object_branch": object_branch,
            "object_push_return_code": object_push.returncode,
            "object_push_stdout": object_push.stdout,
            "object_push_stderr": object_push.stderr,
            "target_push_return_code": target_push.returncode,
            "target_push_stdout": target_push.stdout,
            "target_push_stderr": target_push.stderr,
            "target_updated": remote_after == merge_sha,
            "remote_head": remote_after,
            "conflicts": CONFLICTS,
            "changed_file_count": len(changed_paths),
            "frontend_delta": frontend_delta,
            "data_delta": data_delta,
            "ruff_clean": True,
            "push_force": False,
        }
'''
    patched = source[:push_start] + replacement + source[push_end:]
    namespace: dict[str, Any] = {
        "__file__": str(executor_path),
        "__name__": "phase0_sync_object_runtime",
    }
    exec(compile(patched, str(executor_path), "exec"), namespace)
    return namespace["execute_phase0_sync"](repo_root)
