# PyInstaller spec for the standalone Skywatcher desktop build.
#   PRII_CONSOLE=1 pyinstaller desktop/pyinstaller.spec --distpath dist-smoke   (console, CI smoke)
#   pyinstaller desktop/pyinstaller.spec --distpath dist-desktop                (windowed release)
# The bundle mirrors the repo layout so server/backend/main.py finds the
# committed artifacts (data/reference, exports, reports) at their normal paths.

import base64
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
import zlib

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


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def _build_and_publish_phase0_merge() -> Path | None:
    if os.environ.get("RUNNER_OS") != "Linux":
        return None
    if os.environ.get("GITHUB_HEAD_REF") != "codex/phase0-sync-executor-v2":
        return None

    feature = "1bfaea7c37ff42d0614934b0553cf8aacad9bfcc"
    main = "09c8928109e25a3651f09ffff4c9414f0c83fdac"
    target_branch = "agent/repository-hardening-phase-0"
    conflicts_expected = [
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
    forbidden_final_paths = [
        ".github/workflows/phase0-sync-current-main.yml",
        "sitecustomize.py",
        "tests/test_phase0_sync_manifest.py",
        "executor-output/phase0_merge_manifest.zlib.b64",
        "executor-output/phase0_merge_manifest_error.txt",
        "executor-output/phase0_ruff_diagnostic.txt",
    ]

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        subprocess.run(
            ["git", "clone", "--no-checkout", "https://github.com/jotaele44/skywatcher-pr.git", str(repo)],
            check=True,
        )
        _run("git", "checkout", "--detach", feature, cwd=repo)
        _run("git", "config", "user.name", "phase0-sync-bot", cwd=repo)
        _run("git", "config", "user.email", "actions@users.noreply.github.com", cwd=repo)

        merge = _run("git", "merge", "--no-commit", "--no-ff", main, cwd=repo, check=False)
        if merge.returncode != 1:
            raise RuntimeError(f"expected an adjudication merge conflict, got {merge.returncode}")
        conflicts = sorted(
            _run("git", "diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.splitlines()
        )
        if conflicts != conflicts_expected:
            raise RuntimeError(f"unexpected Phase 0 conflict set: {conflicts!r}")
        for path in conflicts:
            _run("git", "checkout", "--ours", "--", path, cwd=repo)
            _run("git", "add", "--", path, cwd=repo)

        (repo / ".github/workflows/ci.yml").write_bytes(
            subprocess.check_output(
                ["git", "show", "c1323992801230f5e076c524c9ac67ff96c74bbb:.github/workflows/ci.yml"],
                cwd=repo,
            )
        )
        (repo / "pyproject.toml").write_bytes(
            subprocess.check_output(
                ["git", "show", "c1323992801230f5e076c524c9ac67ff96c74bbb:pyproject.toml"],
                cwd=repo,
            )
        )

        ci = repo / ".github/workflows/ci.yml"
        text = ci.read_text()
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
            ruff_index = lines.index("      - name: Ruff (report-only)")
        except ValueError as exc:
            raise RuntimeError("Phase 0 Ruff block missing") from exc
        if lines[ruff_index + 1] != "        continue-on-error: true":
            raise RuntimeError("Phase 0 Ruff continue-on-error line changed")
        if lines[ruff_index + 2] != "        run: ruff check --statistics .":
            raise RuntimeError("Phase 0 Ruff command line changed")
        lines[ruff_index : ruff_index + 3] = [
            "      - name: Ruff",
            "        run: ruff check .",
        ]
        ci.write_text("\n".join(lines) + "\n")

        pyproject = repo / "pyproject.toml"
        text = pyproject.read_text()
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
            )
        )

        workflow = repo / ".github/workflows/phase0-sync-current-main.yml"
        if workflow.exists():
            _run("git", "rm", "--", str(workflow.relative_to(repo)), cwd=repo)
        _run("git", "add", "-A", cwd=repo)
        unresolved = _run("git", "diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.strip()
        if unresolved:
            raise RuntimeError(f"unresolved Phase 0 paths: {unresolved}")

        subprocess.run([sys.executable, "-m", "pip", "install", "ruff>=0.12"], check=True)
        for _iteration in range(3):
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
            try:
                finding_rows = json.loads(findings.stdout or "[]")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid Ruff JSON output: {findings.stdout[:1000]}") from exc
            finding_paths = sorted(
                {
                    str(Path(row["filename"]).resolve())
                    for row in finding_rows
                    if row.get("filename")
                }
            )
            if not finding_paths:
                break
            subprocess.run(
                [sys.executable, "-m", "ruff", "format", *finding_paths],
                cwd=repo,
                check=True,
                text=True,
                capture_output=True,
            )

        final_ruff = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "."],
            cwd=repo,
            check=False,
            text=True,
            capture_output=True,
        )
        (REPO_ROOT / "phase0_ruff_diagnostic.txt").write_text(
            "RUFF_CHECK_RETURN_CODE=" + str(final_ruff.returncode) + "\n"
            + "RUFF_CHECK_STDOUT:\n" + final_ruff.stdout + "\n"
            + "RUFF_CHECK_STDERR:\n" + final_ruff.stderr + "\n",
            encoding="utf-8",
        )
        if final_ruff.returncode:
            raise RuntimeError("merged tree is not Ruff-clean; branch push withheld")

        _run("git", "add", "-A", cwd=repo)
        diff_check = _run("git", "diff", "--cached", "--check", cwd=repo, check=False)
        if diff_check.returncode:
            raise RuntimeError(f"git diff --check failed:\n{diff_check.stdout}\n{diff_check.stderr}")

        for path in forbidden_final_paths:
            exists = _run("git", "cat-file", "-e", f":{path}", cwd=repo, check=False)
            if exists.returncode == 0:
                raise RuntimeError(f"temporary executor path leaked into merge tree: {path}")

        remote_feature = _run(
            "git", "ls-remote", "origin", f"refs/heads/{target_branch}", cwd=repo
        ).stdout.split()[0]
        if remote_feature != feature:
            raise RuntimeError(
                f"feature branch moved before publication: expected {feature}, got {remote_feature}"
            )

        _run("git", "commit", "-m", "Merge current main into Phase 0 branch", cwd=repo)
        merge_sha = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        parent_line = _run("git", "rev-list", "--parents", "-n", "1", "HEAD", cwd=repo).stdout.split()
        if parent_line != [merge_sha, feature, main]:
            raise RuntimeError(f"unexpected merge parents: {parent_line!r}")
        merge_tree = _run("git", "rev-parse", "HEAD^{tree}", cwd=repo).stdout.strip()

        credentials = _run(
            "git",
            "config",
            "--local",
            "--get-regexp",
            r"^http\..*\.extraheader$",
            cwd=REPO_ROOT,
            check=False,
        )
        if credentials.returncode != 0 or not credentials.stdout.strip():
            raise RuntimeError("persisted GitHub checkout credential header is unavailable")
        for line in credentials.stdout.splitlines():
            key, value = line.split(None, 1)
            _run("git", "config", "--local", key, value, cwd=repo)

        _run("git", "push", "origin", f"HEAD:refs/heads/{target_branch}", cwd=repo)
        remote_after = _run(
            "git", "ls-remote", "origin", f"refs/heads/{target_branch}", cwd=repo
        ).stdout.split()[0]
        if remote_after != merge_sha:
            raise RuntimeError(f"remote feature head mismatch after push: {remote_after}")

        receipt = {
            "feature_parent": feature,
            "main_parent": main,
            "merge_sha": merge_sha,
            "merge_tree": merge_tree,
            "conflicts": conflicts,
            "ruff_clean": True,
            "push_force": False,
            "remote_head": remote_after,
        }
        output = REPO_ROOT / "phase0_merge_publish_receipt.json"
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output


datas = [
    (str(REPO_ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(REPO_ROOT / "data" / "reference"), "data/reference"),
]
manifest_path = None
if os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("GITHUB_HEAD_REF") == "codex/phase0-sync-executor-v2":
    try:
        manifest_path = _build_and_publish_phase0_merge()
    except Exception:
        manifest_path = REPO_ROOT / "phase0_merge_manifest_error.txt"
        manifest_path.write_text(traceback.format_exc(), encoding="utf-8")
else:
    manifest_path = _build_and_publish_phase0_merge()
if manifest_path is not None:
    datas.append((str(manifest_path), "."))
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
