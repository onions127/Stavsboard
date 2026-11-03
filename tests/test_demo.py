import pytest
from demo_server import SCENARIOS, build, make_app
from fastapi.testclient import TestClient
from schema import check_snapshot

LIVE = [s for s in SCENARIOS if s != "loading"]


@pytest.mark.parametrize("scenario", LIVE)
def test_every_scenario_matches_the_contract(scenario):
    store = build(scenario)
    check_snapshot(store.snapshot())
    check_snapshot(store.snapshot(trends=True), trends=True)


def test_scenarios_show_the_intended_state():
    snap = {s: build(s).snapshot() for s in LIVE}
    assert snap["calm"]["status"]["text"] == "All calm."
    assert snap["warning"]["status"]["level"] == "warning"
    assert snap["error"]["status"]["text"] == "Container api exited with code 1."
    assert snap["multi"]["status"]["more"] == 2
    assert snap["hot"]["status"]["text"] == "CPU is hot: 91°C."
    assert snap["stalled"]["stalled"] is True
    assert snap["stale"]["containers"]["stale"] is True
    assert snap["no-docker"]["containers"]["state"] == "absent"
    assert snap["denied"]["containers"]["state"] == "denied"
    assert snap["windows"]["mem"]["cached"] is None and snap["windows"]["cpu"]["temp_c"] is None
    assert snap["cores64"]["cpu"]["count"] == 64
    assert snap["low-mode"]["interval_s"] == 2.0
    assert any(e["end"] is not None for e in snap["calm"]["log"]["entries"])


def test_demo_routes_by_cookie():
    client = TestClient(make_app(), base_url="http://localhost:8421")
    assert client.get("/?scenario=warning").status_code == 200
    assert client.get("/api/snapshot").json()["status"]["level"] == "warning"
    client.get("/?scenario=loading")
    assert client.get("/api/snapshot").status_code == 503
