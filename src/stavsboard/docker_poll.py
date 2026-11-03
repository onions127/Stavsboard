"""Container poller on its own thread, so a slow or hung Docker never delays host data.

Read-only: it lists, inspects and reads stats. It never starts, stops or changes containers.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from .store import MODES, Store

log = logging.getLogger("stavsboard")

RESTART_CHECK_S = 30.0  # D13: refresh every container's RestartCount at most this often


def default_factory(timeout: float):
    """A low-level docker API client from the environment (socket / named pipe)."""
    import docker

    return docker.from_env(timeout=timeout).api


def classify(exc: BaseException) -> str:
    """"denied" (no permission), "timeout" (daemon slow: let data go stale) or "absent"."""
    seen = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        text = str(e).lower()
        if isinstance(e, PermissionError) or "permission denied" in text or "access is denied" in text:
            return "denied"
        if isinstance(e, TimeoutError) or "timed out" in text or "timeout" in type(e).__name__.lower():
            return "timeout"
        e = e.__cause__ or e.__context__
    return "absent"


def container_cpu(prev: dict | None, stats: dict) -> tuple[float | None, dict | None]:
    """D15: Δcontainer / Δsystem × 100 = % of Docker's CPUs, across our own polls
    (one_shot stats carry no previous sample)."""
    try:
        cpu = stats["cpu_stats"]
        cur = {"total": cpu["cpu_usage"]["total_usage"], "system": cpu["system_cpu_usage"]}
    except (KeyError, TypeError):
        return None, None
    if not prev:
        return None, cur
    d_sys = cur["system"] - prev["system"]
    d_ctr = cur["total"] - prev["total"]
    if d_sys <= 0 or d_ctr < 0:
        return None, cur
    return min(100.0, d_ctr / d_sys * 100.0), cur


def container_mem(stats: dict) -> int | None:
    """Usage minus inactive page cache, as `docker stats` shows (cgroup v2, then v1)."""
    ms = stats.get("memory_stats") or {}
    usage = ms.get("usage")
    if usage is None:
        return None
    st = ms.get("stats") or {}
    inactive = st.get("inactive_file", st.get("total_inactive_file", 0)) or 0
    return max(0, usage - inactive)


class DockerPoller:
    def __init__(self, store: Store, factory=default_factory, mono=time.monotonic):
        self.store = store
        self.factory = factory
        self.mono = mono
        self._client = None
        self._client_timeout = None
        self._pool: ThreadPoolExecutor | None = None
        self._pool_workers = None
        self._inflight: dict[str, object] = {}  # container id -> future still running (C3)
        self._known: dict[str, dict] = {}  # id -> {"state", "exit_code", "restart_count"}
        self._cpu_prev: dict[str, dict] = {}
        self._last_restart_check = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- one poll ------------------------------------------------------------------------

    def poll_once(self) -> None:
        cfg = MODES[self.store.mode]
        self._ensure_pool(cfg["workers"])
        if self._client is None or self._client_timeout != cfg["timeout_s"]:
            self._close_client()
            try:
                self._client = self.factory(cfg["timeout_s"])
                self._client_timeout = cfg["timeout_s"]
            except Exception as exc:
                self._report_failure(exc)
                return
        try:
            listed = self._client.containers(all=True)  # sparse list: one call (D13)
        except Exception as exc:
            self._report_failure(exc)
            return

        now = self.mono()
        check_restarts = self._last_restart_check is None or now - self._last_restart_check >= RESTART_CHECK_S
        items, to_inspect, to_stat = [], [], []
        for d in listed:
            cid = d.get("Id", "")
            names = d.get("Names") or []
            state = d.get("State")
            if isinstance(state, dict):
                state = state.get("Status")
            item = {"id": cid[:12], "name": names[0].lstrip("/") if names else cid[:12], "state": state,
                    "exit_code": None, "restart_count": None, "cpu": None, "mem": None, "_id": cid}
            known = self._known.get(cid)
            if known is None or known["state"] != state or check_restarts:
                to_inspect.append(item)
            else:
                item["exit_code"], item["restart_count"] = known["exit_code"], known["restart_count"]
            if state == "running":
                to_stat.append(item)
            items.append(item)
        if check_restarts:
            self._last_restart_check = now

        futures = {}
        for item in to_inspect:
            f = self._submit(item["_id"] + ":inspect", self._client.inspect_container, item["_id"])
            if f is not None:
                futures[f] = ("inspect", item)
        for item in to_stat:
            f = self._submit(item["_id"] + ":stats", self._client.stats, item["_id"], stream=False, one_shot=True)
            if f is not None:
                futures[f] = ("stats", item)
        done, _ = wait(futures, timeout=cfg["timeout_s"]) if futures else (set(), set())

        inspected = set()
        for f in done:
            kind, item = futures[f]
            try:
                result = f.result()
            except Exception:
                continue  # that row shows "—"; the list call still succeeded
            if kind == "inspect":
                st = result.get("State") or {}
                item["exit_code"] = st.get("ExitCode")
                item["restart_count"] = result.get("RestartCount")
                inspected.add(item["_id"])
            else:
                item["cpu"], self._cpu_prev[item["_id"]] = container_cpu(self._cpu_prev.get(item["_id"]), result)
                item["mem"] = container_mem(result)

        known = {}
        asked = {i["_id"] for i in to_inspect}
        for item in items:
            cid = item["_id"]
            if cid in asked and cid not in inspected:
                # Inspect didn't finish: keep the old details and ask again next poll.
                old = self._known.get(cid)
                if old is not None:
                    item["restart_count"] = old["restart_count"]
                    if old["state"] == item["state"]:
                        item["exit_code"] = old["exit_code"]
                        known[cid] = old
                continue
            known[cid] = {"state": item["state"], "exit_code": item["exit_code"],
                          "restart_count": item["restart_count"]}
        self._known = known
        live = {i["_id"] for i in items}
        self._cpu_prev = {k: v for k, v in self._cpu_prev.items() if k in live}
        for item in items:
            del item["_id"]
        self.store.put_docker("ok", items)

    def _submit(self, key: str, fn, *args, **kwargs):
        prev = self._inflight.get(key)
        if prev is not None and not prev.done():  # C3: skip while the last call is still busy
            return None
        f = self._pool.submit(fn, *args, **kwargs)
        self._inflight[key] = f
        return f

    def _report_failure(self, exc: BaseException) -> None:
        kind = classify(exc)
        if kind == "timeout":
            return  # keep the last data; the store ages it into "stale"
        self._close_client()
        self._known.clear()
        self._cpu_prev.clear()
        self.store.put_docker(kind)

    def _ensure_pool(self, workers: int) -> None:
        if self._pool is None or self._pool_workers != workers:
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stavsboard-docker")
            self._pool_workers = workers
            self._inflight.clear()

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    # ---- thread --------------------------------------------------------------------------

    def run(self) -> None:
        while not self._stop.is_set():
            t0 = self.mono()
            try:
                self.poll_once()
            except Exception:
                log.exception("docker poll failed")
            cadence = MODES[self.store.mode]["docker_s"]
            self._stop.wait(max(0.0, t0 + cadence - self.mono()))

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="stavsboard-docker-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        self._close_client()
