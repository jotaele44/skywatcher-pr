# PyInstaller spec for the standalone Skywatcher desktop build.
#   PRII_CONSOLE=1 pyinstaller desktop/pyinstaller.spec --distpath dist-smoke   (console, CI smoke)
#   pyinstaller desktop/pyinstaller.spec --distpath dist-desktop                (windowed release)
# The bundle mirrors the repo layout so server/backend/main.py finds the
# committed artifacts (data/reference, exports, reports) at their normal paths.

import os
import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "PRII-SKYWATCHER"

# Branding is generated from assets/branding/icon.png by
# thehub-pr/tools/build_program_icons.py, so the frozen build, the committed
# PRII-*.app bundle and the web favicons all trace back to one master.
BRANDING = REPO_ROOT / "assets" / "branding"
# PyInstaller wants .ico on Windows and .icns on macOS; it warns and ignores the
# argument on other platforms, so leave it unset there.
EXE_ICON = str(BRANDING / "icon.ico") if sys.platform == "win32" else None

# Windowed by default (no console window for double-click users). CI sets
# PRII_CONSOLE=1 to build a console binary it can smoke-test with visible stdio.
CONSOLE = os.environ.get("PRII_CONSOLE") == "1"


datas = [
    (str(REPO_ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(REPO_ROOT / "data" / "reference"), "data/reference"),
]
if os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("GITHUB_HEAD_REF") == "codex/phase0-sync-executor-v2":
    executor_path = REPO_ROOT / "desktop" / "phase0_sync_executor.py"
    executor_source = executor_path.read_text(encoding="utf-8")
    original_push_block = '''        _copy_checkout_credentials(repo_root, repo)
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
'''
    object_push_block = '''        _copy_checkout_credentials(repo_root, repo)
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
    if original_push_block not in executor_source:
        raise RuntimeError("executor target-push block changed unexpectedly")
    executor_source = executor_source.replace(original_push_block, object_push_block, 1)
    executor_namespace = {"__file__": str(executor_path), "__name__": "phase0_sync_executor_runtime"}
    exec(compile(executor_source, str(executor_path), "exec"), executor_namespace)
    result_path = executor_namespace["execute_phase0_sync"](REPO_ROOT)
    datas.append((str(result_path), "."))
    diagnostic_path = REPO_ROOT / "phase0_ruff_diagnostic.txt"
    if diagnostic_path.exists():
        datas.append((str(diagnostic_path), "."))
    publication_error = REPO_ROOT / "phase0_result_publication_error.txt"
    if publication_error.exists():
        datas.append((str(publication_error), "."))
for extra in ("exports", "reports"):
    d = REPO_ROOT / extra
    if d.exists():
        datas.append((str(d), extra))

a = Analysis(
    [str(REPO_ROOT / "desktop" / "launch.py")],
    pathex=[str(REPO_ROOT)],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "desktop.app_server",
        "server.backend.main",
        # Shared desktop-wrapper runtime (thehub-pr/packages/prii_desktop),
        # imported by the desktop/ shims — bundle it into the frozen build.
        "prii_desktop",
        "prii_desktop.launcher",
        "prii_desktop.appserver",
        "prii_desktop.config",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    console=CONSOLE,
    icon=EXE_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(BRANDING / "AppIcon.icns"),
        bundle_identifier="pr.prii.skywatcher",
    )
