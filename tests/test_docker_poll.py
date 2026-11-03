import time

from fakes import Clock, FakeDocker, ctr, stats

from stavsboard.docker_poll import DockerPoller, classify, container_cpu, container_mem
from stavsboard.store import Store


def make(fake=None, mode="accurate"):
    clock = Clock()
    store = Store(mode=mode, mono=clock, wall=clock)
    fake = fake or FakeDocker()
    poller = DockerPoller(store, factory=lambda timeout: fake, mono=clock)
    return poller, store, fake, clock


def running(fake, cid, name, restarts=0):
    fake.containers_list.append(ctr(cid, name))
    fake.inspect[cid] = {"State": {"Status": "running", "ExitCode": 0}, "RestartCount": restarts}


def test_cpu_formula_is_share_of_docker_cpus():
    cpu, prev = container_cpu(None, stats(1_000, 10_000))
    assert cpu is None
    cpu, _ = container_cpu(prev, stats(1_500, 12_000))
    assert cpu == 25.0  # 500 / 2000 * 100


def test_memory_subtracts_inactive_cache():
    assert container_mem(stats(0, 0, usage=300, inactive=100)) == 200
    assert container_mem({"memory_stats": {}}) is None


def test_classify_errors():
    assert classify(PermissionError("x")) == "denied"
    wrapped = RuntimeError("Error while fetching server API version")
    wrapped.__cause__ = OSError("connect: permission denied")
    assert classify(wrapped) == "denied"
    assert classify(Exception("Access is denied.")) == "denied"
    assert classify(TimeoutError()) == "timeout"
    assert classify(Exception("Read timed out. (read timeout=3)")) == "timeout"
    assert classify(FileNotFoundError("pipe not found")) == "absent"


def test_sparse_list_and_targeted_inspect():
    p, store, fake, clock = make()
    running(fake, "aaa111", "postgres")
    fake.stats_seq["aaa111"] = [stats(1_000, 10_000), stats(1_200, 11_000)]
    p.poll_once()
    first_calls = [c[0] for c in fake.calls]
    assert first_calls.count("list") == 1 and first_calls.count("inspect") == 1
    assert fake.calls[0] == ("list", True)
    fake.calls.clear()
    clock.advance(3)
    p.poll_once()
    assert [c[0] for c in fake.calls].count("inspect") == 0  # unchanged: no inspect
    assert ("stats", "aaa111", False, True) in fake.calls  # one_shot stats
    item = store.snapshot()["containers"]["items"][0]
    assert item["name"] == "postgres" and item["cpu"] == 20.0
    assert item["mem"] == 150 * 1024**2


def test_restart_counts_rechecked_every_30s():
    p, store, fake, clock = make()
    running(fake, "a", "api")
    p.poll_once()
    fake.calls.clear()
    clock.advance(31)
    p.poll_once()
    assert ("inspect", "a") in fake.calls


def test_crash_raises_red_warning():
    p, store, fake, clock = make()
    running(fake, "a", "api")
    p.poll_once()
    clock.advance(3)
    fake.containers_list[0]["State"] = "exited"
    fake.inspect["a"] = {"State": {"Status": "exited", "ExitCode": 1}, "RestartCount": 0}
    p.poll_once()
    snap = store.snapshot()
    assert snap["status"]["text"] == "Container api exited with code 1."
    assert snap["containers"]["items"][0]["exit_code"] == 1
    assert snap["levels"]["containers"] == "error"


def test_crash_found_even_if_inspect_is_late():
    fake = FakeDocker()
    p, store, fake, clock = make(fake)
    running(fake, "a", "api")
    p.poll_once()
    clock.advance(3)
    fake.containers_list[0]["State"] = "exited"
    real_inspect = fake.inspect_container
    fake.inspect_container = lambda cid: (_ for _ in ()).throw(TimeoutError())
    p.poll_once()
    assert store.snapshot()["active"] == []
    fake.inspect_container = real_inspect
    fake.inspect["a"] = {"State": {"Status": "exited", "ExitCode": 2}, "RestartCount": 0}
    clock.advance(3)
    p.poll_once()
    assert store.snapshot()["status"]["level"] == "error"


def test_slow_stats_shows_dash_and_is_skipped_next_poll():
    p, store, fake, clock = make()
    running(fake, "a", "api")
    p.poll_once()
    fake.block_stats.clear()
    p_timeout = 3.0
    clock.advance(3)
    t0 = time.monotonic()
    import stavsboard.store as st
    old = st.MODES["accurate"]["timeout_s"]
    st.MODES["accurate"]["timeout_s"] = 0.2  # keep the test fast
    try:
        p.poll_once()
        assert store.snapshot()["containers"]["items"][0]["cpu"] is None
        n_stats = sum(1 for c in fake.calls if c[0] == "stats")
        p.poll_once()  # previous stats call still running: not submitted again (C3)
        assert sum(1 for c in fake.calls if c[0] == "stats") == n_stats
    finally:
        st.MODES["accurate"]["timeout_s"] = old
        fake.block_stats.set()
        p.stop()
    assert time.monotonic() - t0 < p_timeout


def test_absent_denied_and_stale_states():
    p, store, fake, clock = make()
    assert store.snapshot()["containers"]["state"] == "loading"
    fake.list_error = FileNotFoundError("no docker")
    p.poll_once()
    assert store.snapshot()["containers"]["state"] == "absent"
    fake.list_error = PermissionError("permission denied")
    p.poll_once()
    assert store.snapshot()["containers"]["state"] == "denied"
    fake.list_error = None
    p.poll_once()
    snap = store.snapshot()["containers"]
    assert snap["state"] == "ok" and snap["items"] == [] and snap["stale"] is False
    fake.list_error = TimeoutError()
    clock.advance(10)
    p.poll_once()
    snap = store.snapshot()["containers"]
    assert snap["state"] == "ok" and snap["stale"] is True and snap["age_s"] == 10


def test_low_mode_stale_after_30s():
    p, store, fake, clock = make(mode="low")
    p.poll_once()
    clock.advance(20)
    assert store.snapshot()["containers"]["stale"] is False
    clock.advance(11)
    assert store.snapshot()["containers"]["stale"] is True


def test_stop_shuts_down_promptly():
    p, store, fake, clock = make()
    running(fake, "a", "api")
    fake.block_stats.clear()
    p.start()
    t0 = time.monotonic()
    p.stop()
    fake.block_stats.set()
    assert time.monotonic() - t0 < 1.0
