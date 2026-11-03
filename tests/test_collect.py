from fakes import Clock, FakePs, Temp

from stavsboard.collect import HostCollector, ProcessTable, groups, read_memory, read_temp, top_lists
from stavsboard.store import Store, stall_after

GB = 1024**3


def proc(name, cpu=0.0, rss=100, create=1, **kw):
    return {"name": name, "cpu": cpu, "rss": rss, "create": create, **kw}


# ---- processes (D10, C1, AccessDenied, PID reuse) -------------------------------------------

def test_cpu_is_share_of_machine_and_ready_on_second_tick():
    ps = FakePs(cores=4, procs={10: proc("build", cpu=200.0)})
    table = ProcessTable(ps, 4)
    first = table.sample()
    assert first[0]["cpu"] is None  # psutil's first reading only primes
    second = table.sample()
    assert second[0]["cpu"] == 50.0  # 200% of one core = 50% of 4 cores


def test_pid_zero_is_excluded():
    ps = FakePs(procs={0: proc("System Idle Process", cpu=390.0), 4: proc("System")})
    table = ProcessTable(ps, 4)
    table.sample()
    assert [r["pid"] for r in table.sample()] == [4]


def test_access_denied_fields_are_none_but_row_stays():
    ps = FakePs(procs={7: proc("secure", cpu=40.0, rss=500, denied={"cpu"})})
    table = ProcessTable(ps, 4)
    table.sample()
    row = table.sample()[0]
    assert row["cpu"] is None and row["rss"] == 500
    lists = top_lists([row])
    assert lists["by_cpu"] == [] and lists["by_ram"][0]["pid"] == 7


def test_exited_and_reused_pids_are_evicted():
    ps = FakePs(procs={5: proc("old", cpu=80.0, create=1)})
    table = ProcessTable(ps, 1)
    table.sample()
    table.sample()
    ps.procs[5] = proc("new", cpu=10.0, create=2)  # same PID, new process
    rows = table.sample()
    assert rows[0]["name"] == "new" and rows[0]["cpu"] is None  # fresh object, primes again
    del ps.procs[5]
    assert table.sample() == []
    assert table._cache == {}


def test_ranking_uses_three_sample_mean_but_shows_live_value():
    ps = FakePs(cores=1, procs={1: proc("steady", cpu=30.0), 2: proc("spiky", cpu=0.0)})
    table = ProcessTable(ps, 1)
    table.sample()
    for _ in range(3):
        table.sample()
    ps.procs[2]["cpu"] = 50.0  # one spike: live 50 but mean (0+0+50)/3 = 16.7
    lists = top_lists(table.sample())
    assert [r["name"] for r in lists["by_cpu"]] == ["steady", "spiky"]
    assert lists["by_cpu"][1]["cpu"] == 50.0


def test_top_ten_only():
    ps = FakePs(cores=1, procs={i: proc(f"p{i}", cpu=float(i), rss=i) for i in range(1, 15)})
    table = ProcessTable(ps, 1)
    table.sample()
    lists = top_lists(table.sample())
    assert len(lists["by_cpu"]) == 10 and lists["by_cpu"][0]["name"] == "p14"
    assert len(lists["by_ram"]) == 10


def test_groups_sum_by_name():
    rows = [
        {"pid": 1, "name": "chrome.exe", "cpu": 1, "rss": 2 * GB, "cpu_avg": 1.0, "rss_avg": 2 * GB},
        {"pid": 2, "name": "chrome.exe", "cpu": 2, "rss": 1 * GB, "cpu_avg": 2.0, "rss_avg": 1 * GB},
        {"pid": 3, "name": "code", "cpu": 9, "rss": 2.5 * GB, "cpu_avg": 9.0, "rss_avg": 2.5 * GB},
    ]
    g = groups(rows)
    assert g["ram"][0] == {"name": "chrome.exe", "count": 2, "value": 3 * GB}
    assert g["cpu"][0]["name"] == "code"


# ---- memory, swap, temperature --------------------------------------------------------------

def test_memory_linux_has_cached_windows_does_not():
    mem, swap = read_memory(FakePs(linux=True))
    assert mem["used"] == 8 * GB and mem["cached"] == 3.5 * GB
    mem, _ = read_memory(FakePs(linux=False))
    assert mem["cached"] is None
    assert swap["percent"] == 25.0


def test_zero_swap_has_no_percent():
    ps = FakePs()
    ps.swap_total = 0
    ps.swap_used = 0
    _, swap = read_memory(ps)
    assert swap["percent"] is None


def test_temperature_prefers_cpu_chip_and_hides_when_unsupported():
    temps = {
        "acpitz": [Temp("", 99.0, None, None)],
        "coretemp": [Temp("Package id 0", 54.0, 80, 100), Temp("Core 0", 52.0, 80, 100)],
    }
    assert read_temp(FakePs(temps=temps)) == 54.0
    assert read_temp(FakePs(temps={"nvme": [Temp("Composite", 40.0, None, None)]})) is None
    assert read_temp(FakePs()) is None  # no sensors_temperatures attribute (Windows)
    assert read_temp(FakePs(temps={"k10temp": [Temp("Tctl", 61.5, None, None)]})) == 61.5


# ---- collector + store + watchdog (D9, C4) --------------------------------------------------

def make(ps=None, mode="accurate"):
    clock = Clock()
    store = Store(mode=mode, mono=clock, wall=clock)
    return HostCollector(store, ps=ps or FakePs(procs={1: proc("a", cpu=10.0)}), mono=clock), store, clock


def test_tick_fills_snapshot():
    c, store, clock = make(FakePs(cores=4, procs={1: proc("a", cpu=10.0)}, temps={"coretemp": [Temp("x", 50.0, 0, 0)]}))
    c.tick()
    snap = store.snapshot()
    assert snap["cpu"]["count"] == 4 and snap["cpu"]["temp_c"] == 50.0
    assert snap["mem"]["percent"] == 50.0
    assert snap["collected_age_s"] == 0 and snap["stalled"] is False
    assert snap["status"]["text"] == "All calm."


def test_watchdog_flags_stall_after_threshold():
    c, store, clock = make()
    c.tick()
    clock.advance(stall_after("accurate") + 0.5)
    assert store.snapshot()["stalled"] is True
    c.tick()
    assert store.snapshot()["stalled"] is False


def test_low_mode_stall_threshold_is_longer():
    c, store, clock = make(mode="low")
    c.tick()
    clock.advance(4)
    assert store.snapshot()["stalled"] is False


def test_raising_collector_goes_stalled():
    ps = FakePs()
    c, store, clock = make(ps)
    c.tick()

    def boom(*a, **k):
        raise OSError("sensor bus gone")

    ps.virtual_memory = boom
    for _ in range(5):
        clock.advance(1)
        try:
            c.tick()
        except OSError:
            pass
    assert store.snapshot()["stalled"] is True


def test_resume_from_sleep_does_not_carry_sustain():
    ps = FakePs(procs={1: proc("a")})
    ps.total = 99.0
    c, store, clock = make(ps)
    for _ in range(5):
        c.tick()
        clock.advance(1)
    clock.advance(120)  # laptop lid closed
    for _ in range(3):
        c.tick()
        clock.advance(1)
    assert store.snapshot()["active"] == []


def test_mode_switch_changes_interval_and_rings_fill_to_60():
    c, store, clock = make()
    for _ in range(70):
        c.tick()
        clock.advance(1)
    snap = store.snapshot(trends=True)
    assert snap["interval_s"] == 1.0
    assert len(snap["trends"][0]["values"]) == 60
    assert [r["key"] for r in snap["trends"]] == ["cpu", "ram", "swap"]
    store.set_mode("low")
    assert store.snapshot()["interval_s"] == 2.0
