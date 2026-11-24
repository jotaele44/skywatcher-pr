"""Serve Skywatcher's real Launch Pad for the browser end-to-end test.

The desktop app shows the Launch Pad in a native window and talks to it through
pywebview's bridge. A browser test cannot open that window, so this harness
stands in for the window only. Everything else is the shipped code:

* ``GET /`` is the page ``prii_desktop.render_launchpad_html`` renders from
  this repository's ``desktop/config.py``;
* ``POST /bridge/<method>`` calls the same method on the runtime's real
  ``DesktopBridge`` (the spec's ``window.pywebview.api`` shim forwards to it);
* after a launch, the session is applied with the runtime's ``apply_session``
  exactly as the desktop launcher does, and the real Skywatcher backend, built
  by ``make_desktop_app`` (which installs the Guest guard), is mounted at
  ``/app`` and answers requests directly;
* ``GET /session`` reports what the launch produced: mode, start route and the
  non-secret variables the session set. Secret values are never returned.

Test-only. Run from the repository root:
    python frontend/tests/support/launchpad_harness.py --port 8766
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from prii_desktop import DesktopConfig, render_launchpad_html  # noqa: E402
from prii_desktop.launchpad import (  # noqa: E402
    ACCESS_MODE_ENV,
    DesktopBridge,
    apply_session,
    launchpad_spec,
)
from prii_desktop.setup_center import configure  # noqa: E402

from desktop import config as config_module  # noqa: E402

# The page calls these and nothing else; anything outside the list is refused.
BRIDGE_METHODS = {"launchpad_snapshot", "launchpad_launch", "launchpad_set_passphrase", "snapshot"}


def build(state_dir: Path) -> FastAPI:
    config = DesktopConfig.from_module(config_module)
    config.state_dir = state_dir
    # Setup must be complete before the runtime allows a launch.
    configure(config, state_dir / "workspace")
    spec = launchpad_spec(config)
    assert spec is not None, "desktop/config.py declares no LAUNCHPAD"
    bridge = DesktopBridge(config)
    option_envs = {option.env for option in spec.options if option.kind != "secret"}

    harness = FastAPI()

    @harness.get("/", response_class=HTMLResponse)
    def page() -> str:
        return render_launchpad_html(config)

    @harness.post("/bridge/{method}")
    async def call(method: str, request: Request) -> JSONResponse:
        if method not in BRIDGE_METHODS:
            raise HTTPException(404, f"not a Launch Pad bridge call: {method}")
        args = await request.json()
        try:
            result = getattr(bridge, method)(*args)
        except ValueError:
            # The runtime refused the call (for example, a wrong passphrase). The
            # page only needs to know it failed; no detail is passed back.
            return JSONResponse({"error": "The Launch Pad refused this request."}, status_code=400)
        if method == "launchpad_launch":
            # The desktop launcher does exactly this before the backend starts.
            apply_session(spec, bridge.session())
        return JSONResponse(result)

    @harness.get("/session")
    def session() -> dict[str, Any]:
        current = bridge.session()
        if current is None:
            return {"launched": False}
        return {
            "launched": True,
            "mode": os.environ.get(ACCESS_MODE_ENV),
            "start_route": current.start_route,
            "env": {name: os.environ[name] for name in sorted(option_envs) if name in os.environ},
        }

    class Backend:
        """The real backend as an ASGI app, built on the first request after a
        launch, as the desktop launcher builds it after the session is applied."""

        def __init__(self) -> None:
            self.app: Any = None

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if bridge.session() is None:
                await JSONResponse({"detail": "launch first"}, status_code=409)(scope, receive, send)
                return
            if self.app is None:
                from prii_desktop.appserver import make_desktop_app

                config.attach_frontend = False  # the API only; the SPA is not under test here
                self.app = make_desktop_app(config)
            # In the desktop app the backend is served at "/", and the Guest
            # guard matches its allow-list against the request path. Hand the
            # backend that same view: the path without the "/app" mount prefix.
            prefix = scope.get("root_path", "")
            path = scope["path"][len(prefix):] if prefix and scope["path"].startswith(prefix) else scope["path"]
            scope = {**scope, "path": path or "/", "raw_path": (path or "/").encode(), "root_path": ""}
            await self.app(scope, receive, send)

    harness.mount("/app", Backend())

    @harness.get("/ready")
    def ready() -> dict[str, bool]:
        return {"ready": True}

    return harness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    import uvicorn

    with tempfile.TemporaryDirectory(prefix="skywatcher-launchpad-") as tmp:
        os.environ.pop(ACCESS_MODE_ENV, None)
        uvicorn.run(build(Path(tmp)), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
