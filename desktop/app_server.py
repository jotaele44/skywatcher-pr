"""Same-origin ASGI app for the desktop wrapper with Phase 3 security headers."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse  # noqa: E402
from server.backend.main import app  # noqa: E402
from desktop.config import DIST_DIR  # noqa: E402

_PASSTHROUGH_PREFIXES = ("/docs", "/redoc", "/openapi")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
_MISSING_BUILD_CSS = (
    "html,body{height:100%;margin:0}"
    "body{display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
    "background:#0f172a;color:#e2e8f0;text-align:center;padding:0 32px}"
    "h1{font-size:18px;margin:0 0 12px}"
    "p{color:#94a3b8;font-size:14px;max-width:34rem}"
    "code{background:#1e293b;padding:2px 6px;border-radius:4px}"
)
_MISSING_BUILD_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"><title>Setup needed</title>'
    f"<style>{_MISSING_BUILD_CSS}</style></head>"
    "<body><h1>The dashboard isn't built yet</h1>"
    "<p>Run <code>python desktop/setup.py</code> from the repository once (it "
    "needs internet the first time) to build the interface, then reopen the app.</p>"
    "</body></html>"
)

def _index_response():
    index = DIST_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(_MISSING_BUILD_PAGE, status_code=503)

def _apply_security_headers(response):
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response

@app.middleware("http")
async def spa_navigation(request, call_next):
    accept = request.headers.get("accept", "")
    path = request.url.path
    if (
        request.method == "GET"
        and accept.split(",", 1)[0].strip().startswith("text/html")
        and not path.startswith(_PASSTHROUGH_PREFIXES)
        and "." not in path.rsplit("/", 1)[-1]
    ):
        response = _index_response()
    else:
        response = await call_next(request)
    return _apply_security_headers(response)

@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.endswith("/"):
        trimmed = "/" + full_path.strip("/")
        if any(getattr(route, "path", None) == trimmed for route in app.routes):
            return RedirectResponse(trimmed, status_code=307)
    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
            return FileResponse(candidate)
    return _index_response()
