"""Fake psutil and docker clients for collector tests."""

from __future__ import annotations

import threading
from collections import namedtuple
from contextlib import contextmanager

Temp = namedtuple("Temp", "label current high critical")
VMem = namedtuple("VMem", "total available percent used free")
VMemLinux = namedtuple("VMemLinux", "total available percent used free buffers cached")
Swap = namedtuple("Swap", "total used free percent")
MemInfo = namedtuple("MemInfo", "rss vms")


class FakePs:
    """Just enough of psutil. `procs` maps pid -> dict(name, cpu, rss, create, denied=set())."""

    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    class AccessDenied(Error):
        pass

    def __init__(self, cores=4, procs=None, linux=True, temps=None):
        self.cores = cores
        self.procs = procs or {}
        self.linux = linux
        self.total = 25.0
        self.per_core = [25.0] * cores
        self.vm_total = 16 * 1024**3
        self.vm_available = 8 * 1024**3
        self.swap_total = 4 * 1024**3
        self.swap_used = 1024**3
        if temps is not None:
            self.sensors_temperatures = lambda: temps
        ps = self

        class Process:
            def __init__(self, pid=None):
                if pid is None:
                    pid = -1
                    ps.procs.setdefault(-1, {"name": "self", "cpu": 0, "rss": 1, "create": 0})
                if pid not in ps.procs:
                    raise ps.NoSuchProcess()
                self.pid = pid
                self._create = ps.procs[pid]["create"]

            def _p(self):
                p = ps.procs.get(self.pid)
                if p is None:
                    raise ps.NoSuchProcess()
                return p

            def is_running(self):
                p = ps.procs.get(self.pid)
                return p is not None and p["create"] == self._create

            @contextmanager
            def oneshot(self):
                yield

            def name(self):
                p = self._p()
                if "name" in p.get("denied", ()):
                    raise ps.AccessDenied()
                return p["name"]

            def cpu_percent(self, interval=None):
                p = self._p()
                if "cpu" in p.get("denied", ()):
                    raise ps.AccessDenied()
                return p["cpu"]

            def memory_info(self):
                p = self._p()
                if "rss" in p.get("denied", ()):
                    raise ps.AccessDenied()
                return MemInfo(p["rss"], p["rss"])

        self.Process = Process

    def pids(self):
        return [p for p in self.procs if p >= 0]

    def cpu_count(self, logical=True):
        return self.cores

    def cpu_percent(self, interval=None, percpu=False):
        return list(self.per_core) if percpu else self.total

    def virtual_memory(self):
        pct = round((self.vm_total - self.vm_available) / self.vm_total * 100, 1)
        if self.linux:
            return VMemLinux(self.vm_total, self.vm_available, pct, 0, 0, 512 * 1024**2, 3 * 1024**3)
        return VMem(self.vm_total, self.vm_available, pct, 0, 0)

    def swap_memory(self):
        pct = round(self.swap_used / self.swap_total * 100, 1) if self.swap_total else 0.0
        return Swap(self.swap_total, self.swap_used, self.swap_total - self.swap_used, pct)


class FakeDocker:
    """Low-level docker API client stand-in. `containers_list` is what the list call returns."""

    def __init__(self):
        self.containers_list: list[dict] = []
        self.inspect: dict[str, dict] = {}
        self.stats_seq: dict[str, list[dict]] = {}
        self.calls: list[tuple] = []
        self.list_error: BaseException | None = None
        self.block_stats = threading.Event()  # set() to let blocked stats calls finish
        self.block_stats.set()
        self.closed = False

    def containers(self, all=False):
        self.calls.append(("list", all))
        if self.list_error:
            raise self.list_error
        return [dict(c) for c in self.containers_list]

    def inspect_container(self, cid):
        self.calls.append(("inspect", cid))
        return self.inspect[cid]

    def stats(self, cid, stream=True, one_shot=None):
        self.calls.append(("stats", cid, stream, one_shot))
        self.block_stats.wait(10)
        seq = self.stats_seq.get(cid) or [{}]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def close(self):
        self.closed = True


def ctr(cid, name, state="running"):
    return {"Id": cid, "Names": [f"/{name}"], "State": state, "Status": state}


def stats(total, system, usage=200 * 1024**2, inactive=50 * 1024**2):
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": total}, "system_cpu_usage": system},
        "memory_stats": {"usage": usage, "stats": {"inactive_file": inactive}},
    }


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s
