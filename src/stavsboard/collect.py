"""Host collector: CPU, memory, swap, CPU temperature and processes, on its own thread.

Read-only: it only reads psutil values and never signals or changes any process.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import psutil

from .store import MODES, Store

log = logging.getLogger("stavsboard")

TOP_N = 10
SMOOTH_N = 3  # D10: rank by the mean of the last 3 samples
PREFERRED_CHIPS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal")


def read_temp(ps) -> float | None:
    """Hottest CPU sensor in °C, or None where the platform doesn't report one (Windows)."""
    fn = getattr(ps, "sensors_temperatures", None)
    if fn is None:
        return None
    try:
        chips = fn() or {}
    except Exception:  # sensors are best-effort; never break a tick
        return None

    def hottest(entries):
        vals = [e.current for e in entries if e.current is not None and 0 < e.current < 150]
        return max(vals) if vals else None

    for chip in PREFERRED_CHIPS:
        if chip in chips:
            t = hottest(chips[chip])
            if t is not None:
                return t
    for chip, entries in chips.items():
        cpuish = [e for e in entries if "cpu" in chip.lower() or "cpu" in (e.label or "").lower()
                  or "package" in (e.label or "").lower()]
        t = hottest(cpuish)
        if t is not None:
            return t
    return None


class ProcessTable:
    """Cached psutil.Process objects keyed by PID, so per-process CPU is right from the
    second tick. Evicts on exit and on PID reuse."""

    def __init__(self, ps, cpu_count: int):
        self.ps = ps
        self.cpu_count = max(1, cpu_count)
        self._cache: dict[int, dict] = {}

    def sample(self) -> list[dict]:
        ps = self.ps
        rows = []
        try:
            pids = ps.pids()
        except Exception:
            log.exception("could not list processes")
            return rows
        live = set()
        for pid in pids:
            if pid == 0:  # C1: "System Idle Process" on Windows, the scheduler on Linux
                continue
            entry = self._cache.get(pid)
            if entry is not None:
                try:
                    if not entry["proc"].is_running():  # create_time changed: PID reused
                        entry = None
                except ps.Error:
                    entry = None
            if entry is None:
                try:
                    proc = ps.Process(pid)
                except ps.Error:
                    continue
                entry = {"proc": proc, "cpu": deque(maxlen=SMOOTH_N), "rss": deque(maxlen=SMOOTH_N),
                         "primed": False}
                self._cache[pid] = entry
            row = self._read(pid, entry)
            if row is None:
                self._cache.pop(pid, None)
                continue
            live.add(pid)
            rows.append(row)
        for pid in list(self._cache):
            if pid not in live:
                del self._cache[pid]
        return rows

    def _read(self, pid: int, entry: dict) -> dict | None:
        ps, proc = self.ps, entry["proc"]
        name = cpu = rss = None
        try:
            with proc.oneshot():
                try:
                    name = proc.name()
                except ps.AccessDenied:
                    pass
                try:
                    raw = proc.cpu_percent(None)  # the first reading only primes psutil
                    cpu = raw / self.cpu_count if entry["primed"] else None
                    entry["primed"] = True
                except ps.AccessDenied:
                    pass
                try:
                    rss = proc.memory_info().rss
                except ps.AccessDenied:
                    pass
        except ps.NoSuchProcess:  # includes ZombieProcess
            return None
        except ps.Error:
            pass
        if cpu is not None:
            entry["cpu"].append(cpu)
        if rss is not None:
            entry["rss"].append(rss)
        return {
            "pid": pid,
            "name": name,
            "cpu": cpu,
            "rss": rss,
            "cpu_avg": _mean(entry["cpu"]) if cpu is not None else None,
            "rss_avg": _mean(entry["rss"]) if rss is not None else None,
        }


def _mean(values) -> float:
    return sum(values) / len(values)


def top_lists(rows: list[dict]) -> dict:
    def public(r):
        return {"pid": r["pid"], "name": r["name"], "cpu": r["cpu"], "rss": r["rss"]}

    by_cpu = sorted((r for r in rows if r["cpu_avg"] is not None), key=lambda r: -r["cpu_avg"])
    by_ram = sorted((r for r in rows if r["rss_avg"] is not None), key=lambda r: -r["rss_avg"])
    return {"by_cpu": [public(r) for r in by_cpu[:TOP_N]], "by_ram": [public(r) for r in by_ram[:TOP_N]]}


def groups(rows: list[dict], top: int = 3) -> dict:
    """D21: totals per process name, for status-sentence blame."""
    cpu: dict[str, list] = {}
    ram: dict[str, list] = {}
    for r in rows:
        name = r["name"]
        if not name:
            continue
        if r["cpu_avg"] is not None:
            g = cpu.setdefault(name, [0, 0.0])
            g[0] += 1
            g[1] += r["cpu_avg"]
        if r["rss"] is not None:
            g = ram.setdefault(name, [0, 0.0])
            g[0] += 1
            g[1] += r["rss"]

    def ranked(d):
        items = sorted(d.items(), key=lambda kv: -kv[1][1])[:top]
        return [{"name": k, "count": v[0], "value": v[1]} for k, v in items]

    return {"cpu": ranked(cpu), "ram": ranked(ram)}


def read_memory(ps) -> tuple[dict, dict]:
    vm = ps.virtual_memory()
    used = vm.total - vm.available
    cached = None
    if hasattr(vm, "cached"):  # Linux; Windows has no cached figure
        cached = min(vm.cached + getattr(vm, "buffers", 0), vm.available)
    mem = {"total": vm.total, "used": used, "cached": cached, "available": vm.available,
           "percent": vm.percent}
    sw = ps.swap_memory()
    swap = {"total": sw.total, "used": sw.used, "percent": sw.percent if sw.total else None}
    return mem, swap


class HostCollector:
    def __init__(self, store: Store, ps=psutil, mono=time.monotonic):
        self.store = store
        self.ps = ps
        self.mono = mono
        self.cpu_count = ps.cpu_count(logical=True) or 1
        self.procs = ProcessTable(ps, self.cpu_count)
        ps.cpu_percent(None)
        ps.cpu_percent(None, percpu=True)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ticks = 0
        try:
            self._own = ps.Process()
            self._own.cpu_percent(None)
        except Exception:
            self._own = None

    def tick(self) -> None:
        ps = self.ps
        total = ps.cpu_percent(None)
        per_core = ps.cpu_percent(None, percpu=True)
        mem, swap = read_memory(ps)
        rows = self.procs.sample()
        data = {
            "cpu": {"total": total, "per_core": per_core, "count": len(per_core) or self.cpu_count,
                    "temp_c": read_temp(ps)},
            "mem": mem,
            "swap": swap,
            "procs": top_lists(rows),
            "groups": groups(rows),
        }
        self.store.put_host(data)
        self._ticks += 1
        if self._ticks == 60 and self._own is not None:  # OV#5: what Stavsboard itself costs
            try:
                own = self._own.cpu_percent(None) / self.cpu_count
                log.info("Stavsboard's own CPU over the first 60 ticks (%s mode): %.2f%%", self.store.mode, own)
            except Exception:
                pass

    def run(self) -> None:
        while not self._stop.is_set():
            t0 = self.mono()
            try:
                self.tick()
            except Exception:  # keep ticking; the watchdog shows "Collector stalled" if this persists
                log.exception("host tick failed")
            interval = MODES[self.store.mode]["host_s"]
            self._stop.wait(max(0.0, t0 + interval - self.mono()))

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="stavsboard-host", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
