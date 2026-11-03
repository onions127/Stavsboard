"""Hand-written check of the /api/snapshot contract (D5). Used by the API and demo tests."""

NUM = (int, float)
LEVELS = {"good", "warning", "error"}


def _opt(v, types):
    return v is None or isinstance(v, types)


def check_snapshot(s: dict, trends: bool = False) -> None:
    for key in ("version", "server_time", "started_at", "interval_s"):
        assert isinstance(s[key], NUM), key
    assert s["mode"] in ("accurate", "low")
    assert _opt(s["collected_age_s"], NUM)
    assert isinstance(s["stalled"], bool)

    cpu = s["cpu"]
    if cpu is not None:
        assert isinstance(cpu["total"], NUM) and isinstance(cpu["count"], int)
        assert all(isinstance(v, NUM) for v in cpu["per_core"])
        assert _opt(cpu["temp_c"], NUM)
    mem = s["mem"]
    if mem is not None:
        for k in ("total", "used", "available", "percent"):
            assert isinstance(mem[k], NUM), k
        assert _opt(mem["cached"], NUM)
    swap = s["swap"]
    if swap is not None:
        assert isinstance(swap["total"], NUM) and isinstance(swap["used"], NUM)
        assert _opt(swap["percent"], NUM)
        assert (swap["percent"] is None) == (swap["total"] == 0)

    for key in ("by_cpu", "by_ram"):
        rows = s["procs"][key]
        assert len(rows) <= 10
        for r in rows:
            assert set(r) == {"pid", "name", "cpu", "rss"}  # no command lines, users, env
            assert isinstance(r["pid"], int) and _opt(r["name"], str)
            assert _opt(r["cpu"], NUM) and _opt(r["rss"], NUM)

    c = s["containers"]
    assert c["state"] in ("loading", "ok", "absent", "denied")
    assert _opt(c["age_s"], NUM) and isinstance(c["stale"], bool)
    for item in c["items"]:
        assert set(item) == {"id", "name", "state", "exit_code", "crashed", "cpu", "mem"}
        assert isinstance(item["crashed"], bool)
        assert isinstance(item["name"], str)

    for a in s["active"]:
        assert a["level"] in ("warning", "error") and isinstance(a["label"], str)
        assert isinstance(a["start"], NUM)
    assert isinstance(s["log"]["since"], NUM)
    assert len(s["log"]["entries"]) <= 100
    for e in s["log"]["entries"]:
        assert isinstance(e["start"], NUM) and _opt(e["end"], NUM)
        assert e["peak_level"] in ("warning", "error")

    st = s["status"]
    assert st["level"] in LEVELS and isinstance(st["text"], str) and isinstance(st["more"], int)
    assert set(s["levels"]) == {"cpu", "mem", "containers"}
    assert all(v in LEVELS for v in s["levels"].values())
    assert isinstance(s["title"], str) and s["title"].endswith("Stavsboard")

    if trends:
        assert isinstance(s["trends"], list)
        for row in s["trends"]:
            assert {"key", "label", "unit", "values", "warn_at", "crit_at"} <= set(row)
            assert len(row["values"]) <= 60
            assert all(_opt(v, NUM) for v in row["values"])
    else:
        assert "trends" not in s
