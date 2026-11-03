"""Dev-only demo server (D11): the real frontend fed scripted snapshots, one per visual state.

    uv run python tests/demo_server.py            # then open http://localhost:8421/?scenario=warning

It is not part of the `stavsboard` command. Snapshots come from the real Store and warning
logic, driven by a fake clock and scripted samples, so the states match production rules.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import Clock  # noqa: E402

from stavsboard.app import STATIC_DIR, RevalidatingStaticFiles, host_allowed  # noqa: E402
from stavsboard.store import MODES, Store  # noqa: E402

GB = 1024**3
MB = 1024**2

SCENARIOS = [
    "calm", "warning", "error", "multi", "hot", "swap", "long", "windows", "cores4", "cores16",
    "cores64", "no-docker", "denied", "stale", "empty-docker", "low-mode", "stalled",
    "disconnected", "loading",
]

PROCS = [
    ("chrome.exe", 4.1, 2.3 * GB), ("Code.exe", 2.6, 1.1 * GB), ("dockerd", 1.9, 0.9 * GB),
    ("python3", 1.2, 410 * MB), ("postgres", 0.8, 212 * MB), ("node", 0.6, 380 * MB),
    ("systemd-journald", 0.3, 64 * MB), ("sshd", 0.1, 12 * MB), ("redis-server", 0.1, 18 * MB),
    ("cron", 0.0, 4 * MB), ("chrome.exe", 0.4, 0.6 * GB), ("chrome.exe", 0.2, 0.4 * GB),
]


def per_core(n: int, base: float, hot: int | None = None) -> list[float]:
    vals = [max(2.0, min(100.0, base + ((i * 37) % 23) - 8)) for i in range(n)]
    if hot is not None:
        vals[hot] = 96.0
    return vals


def host(*, cores=16, cpu=12.0, hot=None, mem_pct=48.0, total=16 * GB, cached=3.2 * GB, swap_total=4 * GB,
         swap_used=0.2 * GB, temp=54.0, procs=PROCS, blame=None):
    used = total * mem_pct / 100
    rows = [{"pid": 1000 + i, "name": n, "cpu": c, "rss": r} for i, (n, c, r) in enumerate(procs)]
    by_cpu = sorted(rows, key=lambda r: -r["cpu"])[:10]
    by_ram = sorted(rows, key=lambda r: -r["rss"])[:10]
    groups = blame or {"cpu": [{"name": "chrome.exe", "count": 3, "value": 4.7}],
                       "ram": [{"name": "chrome.exe", "count": 3, "value": 3.3 * GB}]}
    return {
        "cpu": {"total": cpu, "per_core": per_core(cores, cpu, hot), "count": cores, "temp_c": temp},
        "mem": {"total": total, "used": used, "cached": None if cached is None else min(cached, total - used),
                "available": total - used, "percent": mem_pct},
        "swap": {"total": swap_total, "used": swap_used,
                 "percent": round(swap_used / swap_total * 100, 1) if swap_total else None},
        "procs": {"by_cpu": by_cpu, "by_ram": by_ram},
        "groups": groups,
    }


def ctr(cid, name, state="running", cpu=0.5, mem=200 * MB, code=None, restarts=0):
    return {"id": cid, "name": name, "state": state, "exit_code": code, "restart_count": restarts,
            "cpu": cpu if state == "running" else None, "mem": mem if state == "running" else None}


CTRS = [ctr("a1", "postgres", cpu=0.6, mem=212 * MB), ctr("b2", "redis", cpu=0.1, mem=18 * MB),
        ctr("c3", "api", cpu=2.4, mem=340 * MB)]


def build(scenario: str) -> Store:
    clock = Clock(time.time() - 3 * 3600)
    store = Store(mode="low" if scenario == "low-mode" else "accurate", mono=clock, wall=clock)

    def tick(n, data, ctrs=CTRS, docker="ok", step=None):
        step = step or MODES[store.mode]["host_s"]
        for i in range(n):
            if docker and i % 3 == 0:
                store.put_docker(docker, ctrs if docker == "ok" else None)
            store.put_host(data)
            clock.advance(step)

    # Earlier trouble, long since over: gives the warnings line a "Last:" item and the log history.
    tick(5, host())
    tick(15, host(cpu=97.0))
    tick(15, host())
    clock.advance(3 * 3600 - 200)

    calm = host()
    if scenario in ("calm", "low-mode", "loading", "disconnected"):
        tick(70, calm)
    elif scenario == "warning":
        blame = {"cpu": [], "ram": [{"name": "chrome.exe", "count": 24, "value": 6.1 * GB}]}
        tick(70, host(mem_pct=91.0, cached=1.0 * GB, blame=blame))
    elif scenario == "error":
        tick(40, calm)
        tick(1, calm, ctrs=CTRS)
        tick(30, calm, ctrs=CTRS[:2] + [ctr("c3", "api", state="exited", code=1)])
    elif scenario == "multi":
        tick(30, calm)
        tick(40, host(cpu=94.0, mem_pct=92.0, cached=0.8 * GB), ctrs=CTRS[:2] + [ctr("c3", "api", state="exited", code=139)])
    elif scenario == "hot":
        tick(70, host(cpu=64.0, temp=91.0, hot=3))
    elif scenario == "swap":
        tick(70, host(mem_pct=95.0, cached=0.3 * GB, swap_used=2.4 * GB))
    elif scenario == "long":
        long_procs = [("com.apple.WebKit.WebContent.really-long-helper-process-name", 31.0, 3.9 * GB)] + PROCS
        long_ctrs = [ctr("d4", "my-company-production-api-gateway-blue-green-canary-1", cpu=1.1)] + CTRS
        blame = {"cpu": [{"name": "com.apple.WebKit.WebContent.really-long-helper-process-name", "count": 12, "value": 61.0}],
                 "ram": []}
        tick(70, host(cpu=96.0, procs=long_procs, blame=blame), ctrs=long_ctrs)
    elif scenario == "windows":
        tick(70, host(cached=None, temp=None, total=32 * GB, mem_pct=36.0, swap_total=5.5 * GB, swap_used=0.8 * GB))
    elif scenario == "cores4":
        tick(70, host(cores=4, cpu=35.0))
    elif scenario == "cores16":
        tick(70, host(cores=16, cpu=23.0, hot=3))
    elif scenario == "cores64":
        tick(70, host(cores=64, cpu=41.0, hot=40))
    elif scenario == "no-docker":
        tick(70, calm, docker="absent")
    elif scenario == "denied":
        tick(70, calm, docker="denied")
    elif scenario == "empty-docker":
        tick(70, calm, ctrs=[])
    elif scenario == "stale":
        tick(10, calm)
        tick(60, calm, docker=None)
    elif scenario == "stalled":
        tick(70, calm)
        clock.advance(12)
    return store


def make_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    stores: dict[str, Store] = {}
    served: dict[str, int] = {}

    def store_for(name: str) -> Store:
        if name not in stores:
            stores[name] = build(name)
        return stores[name]

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host"), False, ""):
            return PlainTextResponse("Unknown host", status_code=400)
        return await call_next(request)

    @app.get("/")
    def index(scenario: str | None = None):
        if scenario is None:
            links = "".join(f'<li><a href="/?scenario={s}">{s}</a></li>' for s in SCENARIOS)
            return HTMLResponse(f"<!doctype html><title>Stavsboard demo</title><h1>Demo scenarios</h1><ul>{links}</ul>")
        if scenario not in SCENARIOS:
            return PlainTextResponse("unknown scenario", status_code=404)
        served[scenario] = 0
        resp = FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
        resp.set_cookie("scenario", scenario, samesite="strict")
        return resp

    @app.get("/api/snapshot")
    def snapshot(request: Request, trends: int = 0):
        name = request.cookies.get("scenario", "calm")
        served[name] = served.get(name, 0) + 1
        if name == "loading" or (name == "disconnected" and served[name] > 2):
            return PlainTextResponse("demo: unreachable", status_code=503)
        return JSONResponse(store_for(name).snapshot(trends=bool(trends)), headers={"Cache-Control": "no-store"})

    @app.post("/api/settings")
    async def settings(request: Request):
        body = await request.json()
        store_for(request.cookies.get("scenario", "calm")).set_mode(body.get("mode", "accurate"))
        return {"mode": body.get("mode")}

    app.mount("/static", RevalidatingStaticFiles(directory=STATIC_DIR), name="static")
    return app


if __name__ == "__main__":
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8421)
    args = p.parse_args()
    print(f"Demo: http://localhost:{args.port}/")
    uvicorn.run(make_app(), host="127.0.0.1", port=args.port, log_level="warning")
