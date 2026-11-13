"""TK5 (Giai đoạn 2): end-to-end — hai cổng Kira THẬT (uvicorn trong luồng, cổng loopback ngẫu nhiên) + hub dùng client thật.
SC6, SC7: không kết nối ra ngoài loopback; không đọc/ghi kho secret thật (khoá + ghim nằm trong thư mục tạm)."""
import json
import socket
import threading
import time

import pytest
import uvicorn

from server import fleet as fl
from server import kira_gateway as kg
from server import peer_client as pc

APPR_A = "a" * 32
APPR_B = "b" * 32
KEY_A = "ab12" * 16
KEY_B = "cd34" * 16


@pytest.fixture(autouse=True)
def _no_external_connect(monkeypatch):
    orig = socket.socket.connect
    violations = []

    def guarded(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if not (str(host).startswith("127.") or str(host) == "::1"):
            violations.append(str(host))                 # ghi lại: fleet có thể nuốt ngoại lệ, nên assert ở teardown
            raise OSError("blocked: ngoài loopback")
        return orig(self, addr)
    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    assert violations == [], f"kết nối ra ngoài loopback: {violations}"


class Machine:
    """Một máy phụ giả: upstream Orbit giả + cổng Kira thật trên loopback."""

    def __init__(self, name, key, appr_id, jobs):
        self.name, self.key, self.appr_id = name, key, appr_id
        self.kills, self.decisions = [], []
        self.jobs = jobs
        self.app = kg.create_app(secret=key.encode(), allowed_ips={"127.0.0.1"}, fetch=self._upstream, machine_name=name)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", proxy_headers=False))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.sock]), daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def _upstream(self, method, path, body=None):
        if (method, path) == ("GET", "/api/jobs"):
            return 200, {"jobs": self.jobs, "summary": {"working": len(self.jobs), "attention": 0, "approvals": 1}}
        if method == "POST" and path.endswith("/kill"):
            self.kills.append(int(path.split("/")[3]))
            return 200, {"ok": True}
        if (method, path) == ("GET", "/api/approvals/kira"):
            return 200, {"approvals": [{"id": self.appr_id, "n": 1, "instance": "g-1", "engine": "gemini", "level": "full",
                                        "expires_in": 100, "fp16": "f" * 16, "state": "pending", "prompt": "KHÔNG ĐƯỢC LỘ"}]}
        if method == "POST" and "/kira/" in path and path.startswith("/api/approvals/"):
            self.decisions.append((path.split("/")[3], path.rsplit("/", 1)[1]))
            return 200, {"ok": True, "state": "x"}
        if (method, path) == ("GET", "/api/ledger/summary"):
            return 200, {"date": "2026-11-13", "engines": {"claude": {"count": 2, "cap": 40, "state": "ok"}},
                         "triggers": {"human_turn": 2}, "outcomes": {"ok": 2}}
        return 404, {}

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(2)
        self.sock.close()


@pytest.fixture
def lab(tmp_path):
    a = Machine("tram-a", KEY_A, APPR_A, [{"id": 3, "instance": "c-1", "engine": "codex", "state": "working", "elapsed": 2.5}])
    b = Machine("tram-b", KEY_B, APPR_B, [{"id": 9, "instance": "r-1", "engine": "claude", "state": "blocked", "elapsed": 7.0}])
    keys = tmp_path / "keys"
    keys.mkdir()
    for n, m in (("may-a", a), ("may-b", b)):
        (keys / f"{n}.key").write_text(m.key + "\n", encoding="ascii")
        (keys / f"{n}.url").write_text(m.url + "\n", encoding="ascii")
    peers = [{"name": "may-a", "url": a.url}, {"name": "may-b", "url": b.url}]
    state = {"peers": peers}
    hub = fl.Fleet(peers_provider=lambda: state["peers"], make_client=pc.make_client, key_dir=str(keys), allow_loopback=True,
                   cache_ttl=0.0, get_budget=10 ** 6, post_budget=10 ** 6, snapshot_deadline=10.0)
    yield hub, a, b, keys, state
    a.close()
    b.close()


def machine(snap, name):
    return next(m for m in snap["machines"] if m["name"] == name)


def test_snapshot_shows_both_machines_with_their_own_data(lab):
    hub, a, b, _, _ = lab
    s = hub.snapshot()
    ma, mb = machine(s, "may-a"), machine(s, "may-b")
    assert ma["reachable"] and mb["reachable"] and ma["machine"] == "tram-a" and mb["machine"] == "tram-b"
    assert ma["jobs"][0]["id"] == 3 and mb["jobs"][0]["id"] == 9 and mb["jobs"][0]["state"] == "blocked"
    assert ma["approvals"][0]["id"] == APPR_A and mb["approvals"][0]["id"] == APPR_B
    assert ma["ledger"]["engines"]["claude"]["count"] == 2
    assert "KHÔNG ĐƯỢC LỘ" not in json.dumps(s, ensure_ascii=False)


def test_actions_reach_exactly_the_chosen_machine(lab):
    hub, a, b, _, _ = lab
    assert hub.act("may-a", "stop", 3) == {"ok": True}
    assert hub.act("may-b", "reject", APPR_B) == {"ok": True}
    assert hub.act("may-b", "defer", APPR_B) == {"ok": True}
    assert a.kills == [3] and b.kills == [] and a.decisions == []
    assert b.decisions == [(APPR_B, "reject"), (APPR_B, "defer")]


def test_key_of_machine_a_does_not_open_machine_b(lab):
    hub, a, b, keys, state = lab
    (keys / "may-b.key").write_text(KEY_A + "\n", encoding="ascii")        # hub nhầm khoá của A cho B
    s = hub.snapshot()
    # hai peer dùng chung khoá ⇒ CẢ HAI bị từ chối ở phía hub, không gửi gì tới máy nào
    assert machine(s, "may-a")["error"] == "duplicate_key" and machine(s, "may-b")["error"] == "duplicate_key"
    assert hub.act("may-b", "stop", 9) == {"ok": False, "error": "duplicate_key"}
    assert a.kills == [] and b.kills == []
    # chỉ B được đăng ký nhưng dùng khoá của A ⇒ cổng B từ chối chữ ký
    state["peers"] = [{"name": "may-b", "url": b.url}]
    s2 = hub.snapshot()
    assert machine(s2, "may-b") == {"name": "may-b", "reachable": False, "error": "unauthorized"}
    assert b.kills == []


def test_wrong_key_is_unauthorized_without_leaking_anything(lab):
    hub, a, b, keys, _ = lab
    (keys / "may-b.key").write_text("ef56" * 16 + "\n", encoding="ascii")       # khoá lạ, không trùng ai
    s = hub.snapshot()
    assert machine(s, "may-a")["reachable"] is True
    assert machine(s, "may-b") == {"name": "may-b", "reachable": False, "error": "unauthorized"}
    assert b.kills == [] and b.decisions == []


def test_one_machine_down_is_isolated_and_the_other_keeps_working(lab):
    hub, a, b, _, _ = lab
    b.close()
    t0 = time.monotonic()
    s = hub.snapshot()
    assert time.monotonic() - t0 < 8
    assert machine(s, "may-a")["reachable"] is True
    assert machine(s, "may-b")["reachable"] is False and machine(s, "may-b")["error"] in ("unreachable", "timeout")
    assert hub.act("may-b", "stop", 9)["ok"] is False
    assert hub.act("may-a", "stop", 3) == {"ok": True}


def test_pin_mismatch_blocks_calls_entirely(lab):
    hub, a, b, keys, state = lab
    state["peers"] = [{"name": "may-a", "url": a.url.replace("127.0.0.1", "127.0.0.2")}]     # config khác URL đã ghim
    s = hub.snapshot()
    assert machine(s, "may-a") == {"name": "may-a", "reachable": False, "error": "pin_mismatch"}
    assert a.kills == []


def test_logs_never_contain_urls_or_keys(lab, caplog):
    caplog.set_level("DEBUG")
    hub, a, b, keys, _ = lab
    hub.snapshot()
    hub.act("may-a", "stop", 3)
    (keys / "may-b.key").write_text("ef56" * 16 + "\n", encoding="ascii")
    hub.snapshot()
    text = caplog.text
    for secret in (KEY_A, KEY_B, "ef56" * 16, a.url, b.url, str(a.port)):
        assert secret not in text, secret


def test_replayed_request_is_rejected_by_the_real_gateway(lab):
    """Một tin đã ký bị gửi lại nguyên văn ⇒ cổng từ chối (nonce dùng một lần)."""
    import http.client
    hub, a, b, _, _ = lab
    captured = {}

    class Spy(pc.PeerClient):
        pass
    c = pc.PeerClient("may-a", a.url, KEY_A.encode(), allow_loopback=True)

    def connect(ip, port, timeout):
        conn = http.client.HTTPConnection(str(ip), port, timeout=timeout)
        orig = conn.request

        def spy(method, path, body=None, headers=None):
            captured.update(method=method, path=path, body=body, headers=dict(headers))
            return orig(method, path, body=body, headers=headers)
        conn.request = spy
        return conn
    c._connect = connect
    assert c.request("GET", "/kira/status")[0] == 200
    conn = http.client.HTTPConnection("127.0.0.1", a.port, timeout=4)
    conn.request(captured["method"], captured["path"], body=captured["body"], headers=captured["headers"])
    assert conn.getresponse().status == 401
    conn.close()
