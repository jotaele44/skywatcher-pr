"""Launch the app as a local desktop window.

Thin shim: the launcher runtime (uvicorn + native window + single-instance lock
+ --smoke CI mode) now lives in the shared ``prii_desktop`` package
(thehub-pr/packages/prii_desktop), installed through an exact pinned optional
dependency so the shared runtime is reproducible across the federation. Only ``desktop/config.py`` is per-repo.

Flags (--no-window / --browser / --route PATH / --smoke) are handled by
``prii_desktop.launch``. See the package for details.
"""

from __future__ import annotations

from prii_desktop import DesktopConfig, launch

from desktop import config


def main() -> None:
    launch(DesktopConfig.from_module(config))


if __name__ == "__main__":
    main()
