"""TK4 (Giai đoạn 2): API hub `/api/fleet*`. Peer là giả; không kết nối, không đọc kho secret thật."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from server import fleet as fl
from server import peer_client as pc

APPR = "0123456789abcdef" * 2
GOOD_STATUS = {"jobs": [{"id": 3, "instance": "c-1", "engine": "codex", "state": "working", "elapsed": 1.5}],
               "summary": {"working": 1}}
GOOD_APPR = {"approvals": []}
GOOD_LEDGER = {"date": "2026-11-13", "engines": {}, "triggers": {}, "outcomes": {}}


class FakeClient:
    log: list = []

    def __init__(self, name, key, routes):
        self.name, self.key, self.routes = name, key, routes

    def fingerprint(self):
        return pc.key_fingerprint(self.key)

    def request(self, method, path, body=None):
        FakeClient.log.append((self.name, method, path, body))
        r = self.routes.get((method, path))
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise pc.PeerError("not_found")
        return 200, r


def base_routes(over=None):
    r = {("GET", "/kira/info"): {"name": "may-2"}, ("GET", "/kira/status"): GOOD_STATUS,
         ("GET", "/kira/approvals"): GOOD_APPR, ("GET", "/kira/ledger"): GOOD_LEDGER,
         ("POST", "/kira/stop"): {"ok": True}, ("POST", f"/kira/approvals/{APPR}/reject"): {"ok": True},
         ("POST", f"/kira/approvals/{APPR}/defer"): {"ok": True}}
    r.update(over or {})
    return r


@pytest.fixture
def hub(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": [
        {"name": "may-2", "url": "http://100.64.0.5:7790"}]}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("ORBIT_PEER_KEY_DIR", str(tmp_path / "keys"))        # không bao giờ chạm kho secret thật
    import server.app as app_module
    importlib.reload(app_module)
    FakeClient.log = []
    holder = {"routes": base_routes()}

    def make_client(name, url, **_):
        return FakeClient(name, name.encode() * 20, holder["routes"])
    app_module.FLEET = fl.Fleet(peers_provider=app_module._fleet_peers, local_provider=app_module._fleet_local,
                                make_client=make_client, cache_ttl=0.0, get_budget=10 ** 6, post_budget=10 ** 6)
    return TestClient(app_module.app), app_module, cfg, holder


def test_snapshot_lists_this_machine_and_configured_peers(hub):
    c, _, _, _ = hub
    d = c.get("/api/fleet").json()
    assert [m["name"] for m in d["machines"]] == ["this", "may-2"]
    assert d["machines"][1]["reachable"] is True and d["machines"][1]["jobs"][0]["id"] == 3
    blob = json.dumps(d)
    assert "100.64" not in blob and "7790" not in blob


def test_feature_is_off_by_default_without_peers(hub):
    c, _, cfg, _ = hub
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    assert [m["name"] for m in c.get("/api/fleet").json()["machines"]] == ["this"]


def test_peers_are_read_fresh_from_config_each_time(hub):
    c, _, cfg, _ = hub
    assert len(c.get("/api/fleet").json()["machines"]) == 2
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": []}}), encoding="utf-8")
    assert len(c.get("/api/fleet").json()["machines"]) == 1


def test_local_view_has_no_prompt_or_pid(hub, _isolated_approvals):
    from server import jobs
    jobs.JOBS.clear()
    j = jobs.create("c-1", "codex", "LỆNH RẤT BÍ MẬT")
    j.pid = 4242
    from server.config import Instance
    _isolated_approvals.create(Instance(name="g-1", engine="gemini", role="Coder"), "PROMPT BÍ MẬT 2", "full")
    c, _, _, _ = hub
    d = c.get("/api/fleet").json()
    blob = json.dumps(d, ensure_ascii=False)
    assert "BÍ MẬT" not in blob and "4242" not in blob
    this = d["machines"][0]
    assert this["jobs"][0]["instance"] == "c-1" and this["approvals"][0]["engine"] == "gemini"
    jobs.JOBS.clear()


# --- hành động ---------------------------------------------------------------------------------------
def test_stop_reject_defer_reach_the_right_peer(hub):
    c, _, _, _ = hub
    assert c.post("/api/fleet/may-2/jobs/3/stop").json() == {"ok": True}
    assert c.post(f"/api/fleet/may-2/approvals/{APPR}/reject").json() == {"ok": True}
    assert c.post(f"/api/fleet/may-2/approvals/{APPR}/defer").json() == {"ok": True}
    assert [(x[1], x[2]) for x in FakeClient.log] == [("POST", "/kira/stop"), ("POST", f"/kira/approvals/{APPR}/reject"),
                                                     ("POST", f"/kira/approvals/{APPR}/defer")]
    assert FakeClient.log[0][3] == {"job_id": 3}


def test_unknown_peer_is_404_and_bad_shapes_are_422_without_any_call(hub):
    c, _, _, _ = hub
    assert c.post("/api/fleet/nope/jobs/3/stop").status_code == 404
    for path in ["/api/fleet/BAD NAME/jobs/3/stop", "/api/fleet/may-2/jobs/0/stop", f"/api/fleet/may-2/jobs/{2 ** 31}/stop",
                 "/api/fleet/may-2/jobs/abc/stop", "/api/fleet/may-2/jobs/-1/stop", "/api/fleet/may-2/approvals/ZZZ/reject",
                 f"/api/fleet/may-2/approvals/{APPR.upper()}/reject", "/api/fleet/may-2/approvals/../x/reject"]:
        r = c.post(path)
        assert r.status_code in (404, 405, 422), path
    assert FakeClient.log == []


def test_there_is_no_approve_and_no_instruct_route(hub):
    c, _, _, _ = hub
    for path in [f"/api/fleet/may-2/approvals/{APPR}/approve", f"/api/fleet/may-2/approvals/{APPR}/decide",
                 "/api/fleet/may-2/instruct", "/api/fleet/may-2/run", "/api/fleet/may-2/turn", "/api/fleet/may-2/jobs/3/kill"]:
        assert c.post(path).status_code in (404, 405), path
    assert c.put("/api/fleet").status_code in (404, 405) and c.post("/api/fleet").status_code in (404, 405)
    assert FakeClient.log == []


@pytest.mark.parametrize("code,status", [("rate_limited", 429), ("not_found", 404), ("not_pending", 409), ("invalid", 422),
                                         ("unauthorized", 502), ("unreachable", 502), ("timeout", 502),
                                         ("bad_response", 502), ("forbidden", 502)])
def test_peer_errors_map_to_http_status_with_short_codes(hub, code, status):
    c, _, _, holder = hub
    holder["routes"] = base_routes({("POST", "/kira/stop"): pc.PeerError(code)})
    r = c.post("/api/fleet/may-2/jobs/3/stop")
    assert r.status_code == status and r.json() == {"ok": False, "error": code}


def test_config_problems_are_409_not_a_server_error(hub):
    c, app_module, cfg, _ = hub
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": [
        {"name": "may-2", "url": "http://100.64.0.5:7790"}, {"name": "may-2", "url": "http://100.64.0.6:7790"}]}}), encoding="utf-8")
    r = c.post("/api/fleet/may-2/jobs/3/stop")
    assert r.status_code == 409 and r.json() == {"ok": False, "error": "duplicate_name"}
    assert FakeClient.log == []


# --- bề mặt cục bộ -----------------------------------------------------------------------------------
def test_foreign_host_and_foreign_origin_are_refused(hub):
    c, _, _, _ = hub
    assert c.get("/api/fleet", headers={"Host": "evil.example"}).status_code == 403
    assert c.post("/api/fleet/may-2/jobs/3/stop", headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post(f"/api/fleet/may-2/approvals/{APPR}/reject", headers={"Origin": "https://attacker.test"}).status_code == 403
    assert FakeClient.log == []


def test_settings_peers_cannot_enable_loopback_or_change_key_dir(hub):
    """Điều kiện 8/9: loopback và thư mục khoá không đặt được từ config.json."""
    c, app_module, cfg, _ = hub
    app_module.FLEET = None                                  # dùng Fleet mặc định của app
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": [
        {"name": "may-2", "url": "http://127.0.0.1:7790", "allow_loopback": True, "key_dir": "C:/x", "key_file": "C:/y"}]}}),
        encoding="utf-8")
    d = c.get("/api/fleet").json()
    m = d["machines"][1]
    assert m["reachable"] is False and m["error"] in ("bad_url", "no_key", "no_pin")
    assert "127.0.0.1" not in json.dumps(d)


def test_fleet_peers_keeps_only_name_and_url(hub):
    _, app_module, cfg, _ = hub
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": [
        {"name": "may-2", "url": "http://100.64.0.5:7790", "allow_loopback": True, "key_dir": "C:/x", "key_file": "y"},
        "chuoi", 5, None]}}), encoding="utf-8")
    peers = app_module._fleet_peers()
    assert peers[0] == {"name": "may-2", "url": "http://100.64.0.5:7790"} and peers[1:] == ["chuoi", 5, None]


def test_default_fleet_rejects_loopback_with_bad_url_even_when_key_and_pin_exist(hub, tmp_path):
    """Có khoá + ghim thật trong thư mục tạm: lỗi phải là bad_url (không phải no_key che lỗi)."""
    c, app_module, cfg, _ = hub
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "may-2.key").write_text("ab12" * 16 + "\n", encoding="ascii")
    (keys / "may-2.url").write_text("http://127.0.0.1:7790\n", encoding="ascii")
    cfg.write_text(json.dumps({"instances": [], "settings": {"peers": [
        {"name": "may-2", "url": "http://127.0.0.1:7790", "allow_loopback": True}]}}), encoding="utf-8")
    app_module.FLEET = None
    m = c.get("/api/fleet").json()["machines"][1]
    assert m == {"name": "may-2", "reachable": False, "error": "bad_url"}
