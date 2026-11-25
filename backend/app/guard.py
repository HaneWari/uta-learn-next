"""Loopback-only guard for the local API, plus the token-bearing index page.

The API binds to loopback, but that alone protects nothing: any web page the
user visits can POST to http://127.0.0.1:8000, and a DNS-rebinding domain can
reach it while pretending to be same-origin. Since this API can delete songs,
download 500 MB packs and run pip, every request has to prove it came from
the app itself:
  * Host must be loopback (kills DNS rebinding),
  * writes must not carry a foreign Origin (kills cross-site POSTs),
  * writes must carry the per-launch token that only our own index.html has.
The token is injected into `index.html` at serve time, so a cross-origin page
cannot read it. Development (`UTALEARN_DEV=1`) skips the token because the
Vite dev server serves its own index.html.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from app.paths import DIST_DIR

DEV = os.environ.get("UTALEARN_DEV") == "1"
TOKEN = secrets.token_urlsafe(32)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def local_guard(request: Request, call_next):
    if (request.url.hostname or "").lower() not in LOCAL_HOSTS:
        return PlainTextResponse("forbidden host", status_code=403)
    if request.method in _UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None:
            if (urlsplit(origin).hostname or "").lower() not in LOCAL_HOSTS:
                return PlainTextResponse("forbidden origin", status_code=403)
        if not DEV and request.headers.get("x-uta-token") != TOKEN:
            return PlainTextResponse("missing token", status_code=403)
    return await call_next(request)


def install(app: FastAPI) -> None:
    app.middleware("http")(local_guard)


_TOKEN_META = f'<meta name="uta-token" content="{TOKEN}">'
_index_cache: tuple[Path, float, str] | None = None


def index_html(dist: Path | None = None) -> str:
    """index.html with the launch token injected (cached per file+mtime)."""
    global _index_cache
    path = (dist or DIST_DIR) / "index.html"
    mtime = path.stat().st_mtime
    if _index_cache and _index_cache[0] == path and _index_cache[1] == mtime:
        return _index_cache[2]
    html = path.read_text(encoding="utf-8")
    if "</head>" in html:
        html = html.replace("</head>", f"    {_TOKEN_META}\n  </head>", 1)
    elif "<head>" in html:
        html = html.replace("<head>", f"<head>\n    {_TOKEN_META}", 1)
    else:
        html = _TOKEN_META + html
    _index_cache = (path, mtime, html)
    return html
