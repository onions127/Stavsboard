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


PROXY = "sterver.tail24d7a.ts.net"


@pytest.mark.parametrize("lan", [False, True])
@pytest.mark.parametrize(
    "host, ok",
    [
        (f"{PROXY}:8443", True),
        (PROXY, True),
        ("STERVER.TAIL24D7A.TS.NET.:8443", True),
        (f"{PROXY}.evil.com", False),
        ("other.tail24d7a.ts.net", False),
        ("tail24d7a.ts.net", False),
        ("attacker.example", False),
        ("localhost:8420", True),
    ],
)
def test_allow_host_names(host, lan, ok):
    assert host_allowed(host, lan, "sterver", [PROXY]) is ok
    # extras are normalized the same way as the Host header
    assert host_allowed(host, lan, "sterver", [" Sterver.Tail24d7a.TS.net. "]) is ok


def test_allow_host_does_not_open_other_names():
    assert host_allowed("attacker.example", False, "box", ["other.name"]) is False
    assert host_allowed("192.168.1.20", False, "box", [PROXY]) is False  # IPs still need --lan
    assert host_allowed("anything", False, "box", ["", "  ", "."]) is False


def test_reverse_proxy_name_end_to_end():
    """Tailscale Serve-style: loopback bind, no --lan, Host and Origin carry the proxy name."""
    store = Store()
    app = create_app(store, lan=False, hostname="sterver", extra_hosts=[PROXY])
    client = TestClient(app, base_url=f"https://{PROXY}:8443", client=("127.0.0.1", 50000))
    assert client.get("/").status_code == 200
    assert client.get("/api/snapshot").status_code == 200
    r = client.post("/api/settings", json={"mode": "low"}, headers={"origin": f"https://{PROXY}:8443"})
    assert r.status_code == 200 and store.mode == "low"
    r = client.post("/api/settings", json={"mode": "accurate"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and store.mode == "low"
    assert client.get("/api/snapshot", headers={"host": "attacker.example"}).status_code == 400


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


# ---- installable app (PWA) ------------------------------------------------------------------


def test_manifest_is_installable(setup):
    client, _ = setup
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"] == m["scope"] == "../"
    purposes = {i["purpose"]: i for i in m["icons"]}
    assert {"any", "maskable", "monochrome"} <= set(purposes)
    sizes = {i["sizes"] for i in m["icons"] if i["purpose"] == "any"}
    assert {"192x192", "512x512"} <= sizes
    for icon in m["icons"]:  # every icon actually ships
        res = client.get(f"/static/{icon['src']}")
        assert res.status_code == 200 and res.content[:8] == b"\x89PNG\r\n\x1a\n", icon["src"]
    assert m["shortcuts"][0]["url"] == "../?tab=trends"


def test_index_links_manifest_and_theme_color(setup):
    client, _ = setup
    page = client.get("/").text
    assert 'rel="manifest" href="static/manifest.webmanifest"' in page
    assert page.count('name="theme-color"') == 2 and "viewport-fit=cover" in page


def test_service_worker_served_from_root(setup):
    client, _ = setup
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    # never caches live data
    assert "api/" in r.text and "return; // live data" in r.text
    # still behind the Host guard
    assert client.get("/sw.js", headers={"host": "attacker.example"}).status_code == 400


def test_service_worker_precaches_files_that_exist(setup):
    import re

    client, _ = setup
    sw = client.get("/sw.js").text
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    paths = re.findall(r'"([^"]+)"', shell)
    assert "./" in paths
    for p in paths:  # one missing file makes the whole install fail
        assert client.get("/" + p.removeprefix("./")).status_code == 200, p
