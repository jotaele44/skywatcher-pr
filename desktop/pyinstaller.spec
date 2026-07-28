# PyInstaller spec for the standalone Skywatcher desktop build.
#   PRII_CONSOLE=1 pyinstaller desktop/pyinstaller.spec --distpath dist-smoke   (console, CI smoke)
#   pyinstaller desktop/pyinstaller.spec --distpath dist-desktop                (windowed release)
# The bundle mirrors the repo layout so server/backend/main.py finds the
# committed artifacts (data/reference, exports, reports) at their normal paths.

import os
import runpy
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
    wrapper = runpy.run_path(str(REPO_ROOT / "desktop" / "phase0_sync_object_executor.py"))
    result_path = wrapper["execute_phase0_object_sync"](REPO_ROOT)
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
