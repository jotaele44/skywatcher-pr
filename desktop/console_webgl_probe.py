"""Native pywebview WebGL acceptance probe for the Phase 3 console."""
from __future__ import annotations
import json
import os
import socket
import threading
import time
from pathlib import Path
import urllib.request

REPORT = Path(__file__).resolve().parents[1] / "reports" / "console" / "phase3" / "DESKTOP_WRAPPER_WEBGL_REPORT.json"

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

def main() -> None:
    import uvicorn
    import webview
    from desktop.app_server import app

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("desktop probe backend did not become healthy")

    result = {"status": "fail", "reason": "probe did not complete"}
    window = webview.create_window("Skywatcher Phase 3 Probe", base + "/console", width=1280, height=860)

    def probe() -> None:
        nonlocal result
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                payload = window.evaluate_js("""
                    (() => {
                      const d = window.__SKYWATCHER_CONSOLE_DIAGNOSTICS__ || null;
                      const canvas = document.querySelector('.maplibregl-canvas');
                      const gl = canvas && (canvas.getContext('webgl2') || canvas.getContext('webgl'));
                      if (!d || !['ready', 'unavailable', 'error'].includes(d.runtimeStatus)) return null;
                      return {
                        diagnostics: d,
                        canvas_count: document.querySelectorAll('.maplibregl-canvas').length,
                        user_agent: navigator.userAgent,
                        webgl_version: gl ? gl.getParameter(gl.VERSION) : null,
                        webgl_renderer: gl ? gl.getParameter(gl.RENDERER) : null,
                        route: location.pathname,
                      };
                    })()
                """)
                if payload:
                    result = {
                        "status": "pass" if payload.get("diagnostics", {}).get("runtimeStatus") == "ready" and payload.get("canvas_count") == 1 else "fail",
                        **payload,
                    }
                    break
            except Exception as exc:
                result = {"status": "fail", "reason": str(exc)}
            time.sleep(0.25)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        window.destroy()

    try:
        webview.start(probe, gui=os.environ.get("PYWEBVIEW_GUI") or None, debug=False)
    finally:
        server.should_exit = True
    if result.get("status") != "pass":
        raise SystemExit(f"native desktop WebGL probe failed: {result}")

if __name__ == "__main__":
    main()
