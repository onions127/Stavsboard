"""The shared snapshot: latest host and container data, 60-sample rings, and the payload."""

from __future__ import annotations

import threading
import time
from collections import deque

from .logic import Engine, RULES, is_crash

# D7: refresh modes. Host/Docker cadences, Docker call timeout and worker count, and when
# container data counts as stale. All seconds.
MODES = {
    "accurate": {"host_s": 1.0, "docker_s": 3.0, "timeout_s": 3.0, "workers": 8, "stale_s": 9.0},
    "low": {"host_s": 2.0, "docker_s": 10.0, "timeout_s": 5.0, "workers": 2, "stale_s": 30.0},
}
RING = 60
_THRESH = {r.key: (r.amber, r.red) for r in RULES}


def stall_after(mode: str) -> float:
    """No fresh host tick for this long = "Collector stalled" (D9): 3s in Accurate, 5s in Low."""
    return MODES[mode]["host_s"] * 2 + 1


class Store:
    def __init__(self, mode: str = "accurate", mono=time.monotonic, wall=time.time):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self._lock = threading.Lock()
        self._mono, self._wall = mono, wall
        self.mode = mode
        self.started_wall = wall()
        self.engine = Engine(self.started_wall)
        self.version = 0
        self._host: dict | None = None
        self._host_mono: float | None = None
        self._docker = {"state": "loading", "items": [], "mono": None}
        self._rings = {k: deque(maxlen=RING) for k in ("cpu", "ram", "swap", "temp")}
        self._ctr_rings: dict[str, deque] = {}

    # ---- writers (collector threads) ---------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        with self._lock:
            self.mode = mode

    def put_host(self, data: dict, mono: float | None = None, wall: float | None = None) -> None:
        """data: {"cpu", "mem", "swap", "procs", "groups"} as built by collect.py."""
        mono = self._mono() if mono is None else mono
        wall = self._wall() if wall is None else wall
        cpu, mem, swap = data["cpu"], data["mem"], data["swap"]
        sample = {
            "cpu": cpu["total"],
            "ram": mem["percent"],
            "swap": swap["percent"],
            "temp": cpu.get("temp_c"),
            "mem_used": mem["used"],
            "swap_used": swap["used"],
            "swap_total": swap["total"],
            "groups": data.get("groups") or {},
        }
        with self._lock:
            self.engine.update_host(sample, mono, wall)
            self._host, self._host_mono = data, mono
            for key in self._rings:
                self._rings[key].append(sample[key])
            self._append_container_rings(mono)
            self.version += 1

    def put_docker(self, state: str, items: list[dict] | None = None, mono: float | None = None,
                   wall: float | None = None) -> None:
        """state "ok" after a successful list call; "absent" or "denied" otherwise. A timed-out
        list call is not reported at all, so the data simply ages into "stale"."""
        mono = self._mono() if mono is None else mono
        wall = self._wall() if wall is None else wall
        with self._lock:
            if state == "ok":
                items = items or []
                self.engine.update_containers(items, mono, wall)
                self._docker = {"state": "ok", "items": items, "mono": mono}
                names = {c["name"] for c in items if c["state"] == "running"}
                for name in list(self._ctr_rings):
                    if name not in names:
                        del self._ctr_rings[name]
            else:
                # Docker is gone or locked: the Containers section hides, so its warnings
                # must not linger in the status sentence unexplained.
                self.engine.update_containers([], mono, wall)
                self._docker = {"state": state, "items": [], "mono": None}
                self._ctr_rings.clear()
            self.version += 1

    def _append_container_rings(self, mono: float) -> None:
        # Container rows share the host tick so every Trends row covers the same 60 samples.
        d = self._docker
        stale = d["mono"] is None or mono - d["mono"] > MODES[self.mode]["stale_s"]
        for c in d["items"]:
            if c["state"] != "running":
                continue
            ring = self._ctr_rings.setdefault(c["name"], deque(maxlen=RING))
            ring.append(None if stale else c.get("cpu"))

    # ---- reader (HTTP) --------------------------------------------------------------------

    def snapshot(self, trends: bool = False) -> dict:
        now_mono, now_wall = self._mono(), self._wall()
        with self._lock:
            mode = self.mode
            cfg = MODES[mode]
            age = None if self._host_mono is None else max(0.0, now_mono - self._host_mono)
            host = self._host or {}
            d = self._docker
            d_age = None if d["mono"] is None else max(0.0, now_mono - d["mono"])
            active = self.engine.active_list()
            status = self.engine.status()
            snap = {
                "version": self.version,
                "server_time": now_wall,
                "started_at": self.started_wall,
                "mode": mode,
                "interval_s": cfg["host_s"],
                "collected_age_s": age,
                "stalled": age is not None and age > stall_after(mode),
                "cpu": host.get("cpu"),
                "mem": host.get("mem"),
                "swap": host.get("swap"),
                "procs": host.get("procs") or {"by_cpu": [], "by_ram": []},
                "containers": {
                    "state": d["state"],
                    "age_s": d_age,
                    "stale": d_age is not None and d_age > cfg["stale_s"],
                    "items": _order_containers(d["items"]),
                },
                "active": [_public_active(e) for e in active],
                "log": {"since": self.started_wall, "entries": self.engine.log_entries()},
                "status": {k: status[k] for k in ("level", "text", "more", "key")},
                "levels": self.engine.section_levels(),
                "title": self.engine.title(),
            }
            if trends:
                snap["trends"] = self._trends(host)
        return snap

    def _trends(self, host: dict) -> list[dict]:
        rows = [
            _row("cpu", "CPU", "%", self._rings["cpu"], *_THRESH["cpu"]),
            _row("ram", "Memory", "%", self._rings["ram"], *_THRESH["ram"]),
        ]
        swap = host.get("swap") or {}
        if swap.get("total"):
            rows.append(_row("swap", "Swap", "%", self._rings["swap"], *_THRESH["swap"]))
        if (host.get("cpu") or {}).get("temp_c") is not None:
            rows.append(_row("temp", "CPU temperature", "°C", self._rings["temp"], *_THRESH["temp"]))
        for name in sorted(self._ctr_rings):
            rows.append(_row(f"ctr:{name}", name, "%", self._ctr_rings[name], None, None))
        return rows


def _row(key, label, unit, ring, warn_at, crit_at) -> dict:
    return {"key": key, "label": label, "unit": unit, "values": list(ring), "warn_at": warn_at,
            "crit_at": crit_at}


def _public_active(e: dict) -> dict:
    keys = ("id", "kind", "subject", "level", "label", "start", "peak_text", "value_text")
    return {k: e.get(k) for k in keys}


def _order_containers(items: list[dict]) -> list[dict]:
    """Crashed first (not deliberate stops), then running, then other stopped containers; by name within each."""

    def rank(c):
        if is_crash(c["state"], c.get("exit_code"), c.get("oom_killed")):
            return 0
        return 1 if c["state"] == "running" else 2

    out = []
    for c in sorted(items, key=lambda c: (rank(c), c["name"].lower())):
        row = {k: c.get(k) for k in ("id", "name", "state", "exit_code", "cpu", "mem")}
        row["crashed"] = is_crash(c["state"], c.get("exit_code"), c.get("oom_killed"))
        out.append(row)
    return out
