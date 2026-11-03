import pytest

from stavsboard import logic
from stavsboard.logic import Engine

GB = 1024**3


def run(engine, samples, start=0.0, step=1.0):
    """Feed one sample per `step` seconds; return the engine."""
    t = start
    for s in samples:
        engine.update_host(s, mono=t, wall=1000 + t)
        t += step
    return t


def host(cpu=10, ram=40, swap=5, temp=None, **extra):
    return {"cpu": cpu, "ram": ram, "swap": swap, "temp": temp, **extra}


def level(engine, key):
    e = engine.active.get(key)
    return e["level"] if e else "good"


# ---- thresholds and sustain windows (D2, D17, D19, D20) -------------------------------

@pytest.mark.parametrize(
    "key, samples, expected",
    [
        # CPU: amber >= 90 held 10s; never red
        ("cpu", [host(cpu=95)] * 10, "good"),
        ("cpu", [host(cpu=95)] * 11, "warning"),
        ("cpu", [host(cpu=100)] * 40, "warning"),
        ("cpu", [host(cpu=95)] * 9 + [host(cpu=50)] + [host(cpu=95)] * 9, "good"),
        # RAM: amber >= 90, red >= 97, both 10s
        ("ram", [host(ram=92)] * 11, "warning"),
        ("ram", [host(ram=98)] * 11, "error"),
        ("ram", [host(ram=92)] * 11 + [host(ram=98)] * 11, "error"),
        # red steps down to amber 3 points below the red line for 10s (D20)
        ("ram", [host(ram=98)] * 11 + [host(ram=93)] * 11, "warning"),
        ("ram", [host(ram=98)] * 11 + [host(ram=95)] * 30, "error"),
        # clears 10 points below amber for 10s
        ("ram", [host(ram=92)] * 11 + [host(ram=79)] * 11, "good"),
        ("ram", [host(ram=92)] * 11 + [host(ram=85)] * 30, "warning"),
        ("ram", [host(ram=92)] * 11 + [host(ram=79)] * 9, "warning"),
        # swap counts only with RAM >= 90, for 30s (D19)
        ("swap", [host(swap=60, ram=50)] * 40, "good"),
        ("swap", [host(swap=60, ram=91)] * 31, "warning"),
        ("swap", [host(swap=60, ram=91)] * 29, "good"),
        ("swap", [host(swap=85, ram=91)] * 31, "error"),
        ("swap", [host(swap=60, ram=91)] * 31 + [host(swap=60, ram=79)] * 11, "good"),
        # no swap at all: never warns
        ("swap", [host(swap=None, ram=99)] * 40, "good"),
        # temperature: amber >= 85, red >= 95, 10s (D17)
        ("temp", [host(temp=88)] * 11, "warning"),
        ("temp", [host(temp=96)] * 11, "error"),
        ("temp", [host(temp=96)] * 11 + [host(temp=91)] * 11, "warning"),
        ("temp", [host(temp=96)] * 11 + [host(temp=74)] * 11, "good"),
        ("temp", [host(temp=None)] * 20, "good"),
    ],
)
def test_threshold_table(key, samples, expected):
    e = Engine(started_wall=1000)
    run(e, samples)
    assert level(e, key) == expected


def test_red_is_not_delayed_by_amber_raise():
    e = Engine(started_wall=0)
    # 92% for 5s, then 98%: red should land 10s after it crossed 97, not 10s after amber.
    t = run(e, [host(ram=92)] * 5 + [host(ram=98)] * 11)
    assert level(e, "ram") == "error"
    assert t == 16


def test_resume_gap_resets_sustain_windows():
    e = Engine(started_wall=0)
    e.update_host(host(cpu=99), mono=0, wall=0)
    e.update_host(host(cpu=99), mono=1, wall=1)
    # machine slept 60s; the next sample must not count the gap as "held"
    e.update_host(host(cpu=99), mono=61, wall=61)
    assert level(e, "cpu") == "good"
    run(e, [host(cpu=99)] * 11, start=62)
    assert level(e, "cpu") == "warning"


# ---- warning log (D3) -------------------------------------------------------------------

def test_log_records_ongoing_then_closed_entry_with_peak():
    e = Engine(started_wall=1000)
    t = run(e, [host(ram=92)] * 11 + [host(ram=95)] * 3)
    entry = e.log_entries()[0]
    assert entry["end"] is None and entry["label"] == "RAM above 90%"
    run(e, [host(ram=50)] * 11, start=t)
    entry = e.log_entries()[0]
    assert entry["end"] is not None
    assert entry["peak_text"] == "95%"
    assert e.active == {}


def test_log_keeps_last_100():
    e = Engine(started_wall=0)
    t = 0.0
    for _ in range(120):
        t = run(e, [host(cpu=99)] * 11 + [host(cpu=10)] * 11, start=t)
    entries = e.log_entries()
    assert len(entries) == logic.LOG_SIZE
    assert entries[0]["id"] == 120


def test_peak_level_survives_step_down():
    e = Engine(started_wall=0)
    run(e, [host(ram=98)] * 11 + [host(ram=93)] * 11)
    entry = e.log_entries()[0]
    assert entry["level"] == "warning" and entry["peak_level"] == "error"
    assert entry["label"] == "RAM above 90%"


# ---- containers (D4, D13) ---------------------------------------------------------------

def ctr(state, code=None, restarts=0, cid="a1", name="api"):
    return {"id": cid, "name": name, "state": state, "exit_code": code, "restart_count": restarts}


def test_seen_crash_is_red_and_clears_when_running_again():
    e = Engine(started_wall=0)
    e.update_containers([ctr("running")], 0, 0)
    e.update_containers([ctr("exited", code=1)], 3, 3)
    assert e.status()["level"] == "error"
    assert e.status()["text"] == "Container api exited with code 1."
    assert e.title() == "● api exited · Stavsboard"
    e.update_containers([ctr("running")], 6, 6)
    assert e.active == {}
    assert e.log_entries()[0]["end"] == 6


def test_exit_zero_and_already_exited_do_not_warn():
    e = Engine(started_wall=0)
    e.update_containers([ctr("running", cid="a"), ctr("exited", code=2, cid="b", name="old")], 0, 0)
    e.update_containers([ctr("exited", code=0, cid="a"), ctr("exited", code=2, cid="b", name="old")], 3, 3)
    assert e.active == {}


def test_removed_container_clears_warning():
    e = Engine(started_wall=0)
    e.update_containers([ctr("running")], 0, 0)
    e.update_containers([ctr("exited", code=137)], 3, 3)
    e.update_containers([], 6, 6)
    assert e.active == {}


def test_restart_loop_three_in_five_minutes():
    e = Engine(started_wall=0)
    e.update_containers([ctr("running", restarts=0)], 0, 0)
    e.update_containers([ctr("running", restarts=2)], 30, 30)
    assert e.active == {}
    e.update_containers([ctr("running", restarts=3)], 60, 60)
    assert e.status()["text"] == "Container api keeps restarting."
    # quiet for more than 5 minutes: clears
    e.update_containers([ctr("running", restarts=3)], 400, 400)
    assert e.active == {}


# ---- status sentence and title (DR4, DR17, D21) -----------------------------------------

def test_calm():
    e = Engine(started_wall=0)
    run(e, [host()] * 3)
    assert e.status() == {"level": "good", "text": "All calm.", "more": 0, "key": "calm"}
    assert e.title() == "Stavsboard"


def test_ram_blame_grouped_by_name():
    groups = {"ram": [{"name": "chrome.exe", "count": 24, "value": 6.1 * GB}], "cpu": []}
    e = Engine(started_wall=0)
    run(e, [host(ram=92, mem_used=14.6 * GB, groups=groups)] * 11)
    assert e.status()["text"] == "Memory is high: chrome.exe (24 processes) is using 6.1 GB."
    assert e.title() == "● RAM 92% · Stavsboard"


def test_single_process_blame_and_no_clear_culprit():
    e = Engine(started_wall=0)
    groups = {"cpu": [{"name": "cc1plus", "count": 1, "value": 60.0}], "ram": []}
    run(e, [host(cpu=95, groups=groups)] * 11)
    assert e.status()["text"] == "CPU is busy: cc1plus is using 60%."
    e2 = Engine(started_wall=0)
    groups = {"cpu": [{"name": "a", "count": 1, "value": 10.0}], "ram": []}
    run(e2, [host(cpu=95, groups=groups)] * 11)
    assert e2.status()["text"] == "CPU is busy."


def test_worst_first_and_more_count():
    e = Engine(started_wall=0)
    t = run(e, [host(cpu=95, ram=92)] * 11)
    e.update_containers([ctr("running")], t, t)
    e.update_containers([ctr("exited", code=1)], t + 1, t + 1)
    st = e.status()
    assert st["level"] == "error" and st["more"] == 2
    levels = e.section_levels()
    assert levels == {"cpu": "warning", "mem": "warning", "containers": "error"}


def test_hot_cpu_sentence():
    e = Engine(started_wall=0)
    run(e, [host(temp=91)] * 11)
    assert e.status()["text"] == "CPU is hot: 91°C."
    assert e.title() == "● CPU 91°C · Stavsboard"


def test_swap_sentence():
    e = Engine(started_wall=0)
    run(e, [host(ram=95, swap=55, swap_used=2.2 * GB, swap_total=4 * GB)] * 31)
    texts = {w["kind"]: w for w in e.active_list()}
    assert "swap" in texts
    status = logic.compose_status([texts["swap"]], e._last_sample)
    assert status["text"] == "Swap is busy: 2.2 GB of 4.0 GB in use."
