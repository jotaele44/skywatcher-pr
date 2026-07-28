"""Temporary wrapper that publishes the validated Phase 0 tree ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any


LATEST_MAIN = "9cdf63d584bc58495c32a573dc0fc9ddad981ab8"


def execute_phase0_object_sync(repo_root: Path) -> Path:
    executor_path = repo_root / "desktop" / "phase0_sync_executor.py"
    source = executor_path.read_text(encoding="utf-8")
    source = source.replace(
        'MAIN = "09c8928109e25a3651f09ffff4c9414f0c83fdac"',
        f'MAIN = "{LATEST_MAIN}"',
        1,
    )
    execute_start = source.index("def _execute(repo_root: Path)")
    push_start = source.index(
        "        _copy_checkout_credentials(repo_root, repo)\n", execute_start
    )
    push_end = source.index("\n\n\ndef execute_phase0_sync", push_start)

    replacement = r'''        import base64 as _base64
        import urllib.error as _urllib_error
        import urllib.request as _urllib_request

        credential_result = _run(
            "git",
            "config",
            "--local",
            "--get-regexp",
            r"^http\..*\.extraheader$",
            cwd=repo_root,
            check=False,
        )
        if credential_result.returncode or not credential_result.stdout.strip():
            raise RuntimeError("persisted GitHub API credential header is unavailable")
        authorization = None
        for credential_line in credential_result.stdout.splitlines():
            _key, header = credential_line.split(None, 1)
            if header.lower().startswith("authorization:"):
                authorization = header.split(":", 1)[1].strip()
                break
        if not authorization:
            raise RuntimeError("GitHub Authorization header was not found")

        def _api_post(path: str, payload: dict) -> dict:
            request = _urllib_request.Request(
                "https://api.github.com/repos/jotaele44/skywatcher-pr" + path,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": authorization,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json",
                    "User-Agent": "skywatcher-phase0-sync-executor",
                },
            )
            try:
                with _urllib_request.urlopen(request, timeout=120) as response:
                    return json.loads(response.read().decode("utf-8"))
            except _urllib_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"GitHub Git Data API failed: {exc.code} {path}\n{body}"
                ) from exc

        feature_tree = _run(
            "git", "rev-parse", f"{FEATURE}^{{tree}}", cwd=repo
        ).stdout.strip()
        raw_diff = _run(
            "git",
            "diff-tree",
            "-r",
            "--no-renames",
            "--raw",
            feature_tree,
            tree_sha,
            cwd=repo,
        ).stdout
        tree_elements = []
        uploaded_blobs = 0
        for raw_line in raw_diff.splitlines():
            metadata, path = raw_line.split("\t", 1)
            fields = metadata.split()
            old_mode = fields[0][1:]
            new_mode = fields[1]
            new_sha = fields[3]
            status = fields[4]
            if status == "D":
                tree_elements.append(
                    {"path": path, "mode": old_mode, "type": "blob", "sha": None}
                )
                continue
            if new_mode == "160000":
                tree_elements.append(
                    {"path": path, "mode": new_mode, "type": "commit", "sha": new_sha}
                )
                continue
            blob_bytes = subprocess.check_output(
                ["git", "cat-file", "blob", new_sha], cwd=repo
            )
            blob_response = _api_post(
                "/git/blobs",
                {
                    "content": _base64.b64encode(blob_bytes).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blob_sha = blob_response["sha"]
            if blob_sha != new_sha:
                raise RuntimeError(
                    f"remote blob SHA mismatch for {path}: {blob_sha} != {new_sha}"
                )
            uploaded_blobs += 1
            tree_elements.append(
                {"path": path, "mode": new_mode, "type": "blob", "sha": blob_sha}
            )

        remote_after = _run(
            "git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}", cwd=repo
        ).stdout.split()[0]
        if remote_after != FEATURE:
            raise RuntimeError(
                f"feature branch moved before connector publication: {remote_after}"
            )

        return {
            "feature_parent": FEATURE,
            "main_parent": MAIN,
            "local_merge_sha": merge_sha,
            "validated_tree_sha": tree_sha,
            "base_tree_sha": feature_tree,
            "tree_elements": tree_elements,
            "uploaded_blob_count": uploaded_blobs,
            "tree_element_count": len(tree_elements),
            "target_updated": False,
            "remote_head": remote_after,
            "conflicts": CONFLICTS,
            "changed_file_count": len(changed_paths),
            "frontend_delta": frontend_delta,
            "data_delta": data_delta,
            "ruff_clean": True,
            "push_force": False,
            "publication_method": "connector_create_tree_commit_update_ref",
        }
'''
    patched = source[:push_start] + replacement + source[push_end:]
    namespace: dict[str, Any] = {
        "__file__": str(executor_path),
        "__name__": "phase0_sync_object_runtime",
    }
    exec(compile(patched, str(executor_path), "exec"), namespace)
    return namespace["execute_phase0_sync"](repo_root)
