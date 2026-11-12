"""HTTP: the snapshot API, the refresh-mode setting and the static page."""

from __future__ import annotations

import ipaddress
import json
import mimetypes
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .store import MODES, Store

STATIC_DIR = Path(str(files("stavsboard") / "static"))
mimetypes.add_type("application/manifest+json", ".webmanifest")  # not in every OS's MIME table
LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}
MAX_SETTINGS_BODY = 1024  # bytes; {"mode": "accurate"} is 20
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers re-check (ETag) on every load, so an upgraded install
    never pairs a new index.html with a cached old app.js or app.css."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _split_host(host: str) -> str | None:
    """Host header -> bare lowercase name or IP (port and IPv6 brackets removed)."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return None
        name, rest = host[1:end], host[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        try:
            ipaddress.IPv6Address(name)
        except ValueError:
            return None
        return name
    if host.count(":") > 1:
        return None  # an IPv6 Host must be bracketed
    name, _, port = host.partition(":")
    if _ and not port.isdigit():
        return None
    return name.rstrip(".") or None


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def normalize_host_names(names: Iterable[str]) -> frozenset[str]:
    """--allow-host values -> lowercase names without a trailing dot (empties dropped)."""
    return frozenset(n for n in (raw.strip().lower().rstrip(".") for raw in names) if n)


def host_allowed(host: str | None, lan: bool, hostname: str, extra_hosts: Iterable[str] = ()) -> bool:
    """D13 DNS-rebinding guard. Without --lan: localhost, 127.0.0.1, [::1]. With --lan, also any
    IP literal and this machine's own name (plain or .local). Names passed with --allow-host
    (e.g. a reverse proxy's name) are accepted exactly, with or without --lan."""
    if not host:
        return False
    name = _split_host(host)
    if name is None:
        return False
    if name in LOCAL_NAMES:
        return True
    if name in normalize_host_names(extra_hosts):
        return True
    if not lan:
        return False
    own = hostname.strip().lower().rstrip(".")
    return _is_ip(name) or name in {own, f"{own}.local"}


def origin_matches(origin: str, host: str | None) -> bool:
    if not host:
        return False
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == host.strip().lower()


def create_app(store: Store, *, lan: bool = False, hostname: str = "", extra_hosts: Iterable[str] = (),
               static_dir: Path = STATIC_DIR) -> FastAPI:
    app = FastAPI(title="Stavsboard", docs_url=None, redoc_url=None, openapi_url=None)
    allowed_extra = normalize_host_names(extra_hosts)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host"), lan, hostname, allowed_extra):
            return PlainTextResponse("Unknown host", status_code=400)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/api/snapshot")
    def snapshot(trends: int = 0):
        return JSONResponse(store.snapshot(trends=bool(trends)), headers={"Cache-Control": "no-store"})

    @app.post("/api/settings")
    async def settings(request: Request):
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return PlainTextResponse("Send JSON", status_code=415)
        origin = request.headers.get("origin")
        if origin is not None and not origin_matches(origin, request.headers.get("host")):
            return PlainTextResponse("Cross-site request refused", status_code=403)
        raw = b""
        async for chunk in request.stream():  # capped: anyone on the LAN can reach this
            raw += chunk
            if len(raw) > MAX_SETTINGS_BODY:
                return PlainTextResponse("Request too large", status_code=413)
        try:
            body = json.loads(raw)
        except ValueError:
            return PlainTextResponse("Bad JSON", status_code=400)
        mode = body.get("mode") if isinstance(body, dict) else None
        if mode not in MODES:
            return PlainTextResponse("mode must be 'accurate' or 'low'", status_code=400)
        store.set_mode(mode)
        return {"mode": mode}

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    def service_worker():
        # Served from the root, not /static/, so the installed app's worker covers the whole page.
        return FileResponse(static_dir / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    app.mount("/static", RevalidatingStaticFiles(directory=static_dir), name="static")
    return app
