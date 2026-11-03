import pytest
from fakes import Clock, FakePs
from fastapi.testclient import TestClient
from schema import check_snapshot

from stavsboard.app import create_app, host_allowed
from stavsboard.collect import HostCollector
from stavsboard.store import Store


@pytest.mark.parametrize(
    "host, lan, ok",
    [
        ("localhost", False, True),
        ("localhost:8420", False, True),
        ("LOCALHOST:8420", False, True),
        ("127.0.0.1:8420", False, True),
        ("[::1]:8420", False, True),
        ("[::1]", False, True),
        ("192.168.1.20:8420", False, False),
        ("myserver:8420", False, False),
        ("evil.example.com", False, False),
        ("", False, False),
        (None, False, False),
        ("localhost:abc", False, False),
        ("::1", False, False),
        ("[::1", False, False),
        # --lan: any IP literal, own hostname, hostname.local
        ("192.168.1.20:8420", True, True),
        ("10.0.0.5", True, True),
        ("[fe80::1]:8420", True, True),
        ("myserver:8420", True, True),
        ("MyServer.local:8420", True, True),
        ("myserver.", True, True),
        ("evil.example.com", True, False),
        ("myserver.evil.com", True, False),
        ("1.2.3.4.nip.io", True, False),
        ("[not-ip]:80", True, False),
    ],
)
def test_host_allowed(host, lan, ok):
    assert host_allowed(host, lan, "MyServer") is ok


@pytest.fixture
def setup():
    clock = Clock()
    store = Store(mono=clock, wall=clock)
    collector = HostCollector(store, ps=FakePs(procs={1: {"name": "a", "cpu": 5.0, "rss": 10, "create": 1}}), mono=clock)
    for _ in range(3):
        collector.tick()
        clock.advance(1)
    app = create_app(store, lan=False, hostname="box")
    return TestClient(app, base_url="http://localhost:8420"), store


def test_snapshot_schema_both_forms(setup):
    client, _ = setup
    r = client.get("/api/snapshot")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    check_snapshot(r.json())
    r = client.get("/api/snapshot?trends=1")
    check_snapshot(r.json(), trends=True)


def test_foreign_host_is_rejected(setup):
    client, _ = setup
    r = client.get("/api/snapshot", headers={"host": "attacker.example:8420"})
    assert r.status_code == 400


def test_index_and_static_served_with_security_headers(setup):
    client, _ = setup
    r = client.get("/")
    assert r.status_code == 200 and "Stavsboard" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/fonts/schibsted-grotesk-var.woff2").status_code == 200


# Regression: FINDING-005 — static files had no Cache-Control, so browsers reused an old
# app.js/app.css after an upgrade. Found by /design-review on 2026-11-03.
def test_static_files_revalidate(setup):
    client, _ = setup
    for path in ("/static/app.js", "/static/app.css", "/static/theme.js"):
        r = client.get(path)
        assert r.headers["cache-control"] == "no-cache" and r.headers.get("etag"), path


def test_settings_post_rules(setup):
    client, store = setup
    ok = client.post("/api/settings", json={"mode": "low"})
    assert ok.status_code == 200 and store.mode == "low"
    assert client.get("/api/snapshot").json()["interval_s"] == 2.0
    # form post (what a cross-site <form> can send without preflight): 415
    r = client.post("/api/settings", content="mode=accurate",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
    # JSON with a foreign Origin: 403
    r = client.post("/api/settings", json={"mode": "accurate"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/settings", json={"mode": "accurate"}, headers={"origin": "null"})
    assert r.status_code == 403
    # matching Origin is fine; so is a remote LAN viewer (D16)
    r = client.post("/api/settings", json={"mode": "accurate"}, headers={"origin": "http://localhost:8420"})
    assert r.status_code == 200 and store.mode == "accurate"
    # bad values
    assert client.post("/api/settings", json={"mode": "turbo"}).status_code == 400
    assert client.post("/api/settings", content="{", headers={"content-type": "application/json"}).status_code == 400
    assert store.mode == "accurate"


def test_lan_viewer_can_change_mode():
    store = Store()
    app = create_app(store, lan=True, hostname="box")
    client = TestClient(app, base_url="http://192.168.1.20:8420", client=("192.168.1.31", 50000))
    r = client.post("/api/settings", json={"mode": "low"}, headers={"origin": "http://192.168.1.20:8420"})
    assert r.status_code == 200 and store.mode == "low"


def test_no_write_routes_beyond_settings(setup):
    client, _ = setup
    routes = {(m, r.path) for r in client.app.routes for m in getattr(r, "methods", ()) or ()}
    writes = {(m, p) for m, p in routes if m not in ("GET", "HEAD")}
    assert writes == {("POST", "/api/settings")}


# Regression: review finding 1 — POST /api/settings buffered any body size, so a LAN client
# could exhaust memory. Found by /review on 2026-11-03.
def test_settings_body_is_capped(setup):
    client, store = setup
    big = '{"mode":"low","pad":"' + "x" * 5000 + '"}'
    r = client.post("/api/settings", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and store.mode == "accurate"
