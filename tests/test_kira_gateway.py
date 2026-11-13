"""Cổng Kira (bước 1, mức xem + dừng): HMAC từng tin + nonce + allowlist IP + giới hạn tần suất.
MỌI test mock upstream (không gọi Orbit thật, không đọc ~/.secret, không mở cổng mạng)."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from server import kira_gateway as kg

SECRET = b"k" * 32
CLIENT_IP = "testclient"          # TestClient của Starlette khai client host này
APPR_ID = "0123456789abcdef" * 2


def _sign(method, path, body=b"", *, ts, nonce, secret=SECRET):
    msg = f"{method}\n{path}\n{ts}\n{nonce}\n".encode() + body
    return {"X-Kira-Ts": str(ts), "X-Kira-Nonce": nonce,
            "X-Kira-Sig": hmac.new(secret, msg, hashlib.sha256).hexdigest()}


class Upstream:
    def __init__(self):
        self.ledger = {"date": "2026-11-13", "engines": {"claude": {"count": 3, "cap": 40, "state": "ok", "x": "y"}},
                       "triggers": {"human_turn": 3, "evil": 9}, "outcomes": {"ok": 3}, "secret": "leak"}
        self.calls = []
        self.jobs = [{"id": 7, "instance": "c-1", "engine": "codex", "prompt": "BÍ MẬT prompt",
                      "state": "working", "seen": False, "pid": 4242, "started_at": 1.0,
                      "elapsed": 3.2, "last_line": "dòng log nhạy cảm", "silence": 0.1,
                      "exit_code": None, "error": ""}]

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/api/jobs"):
            return 200, {"jobs": self.jobs, "summary": {"blocked": 0, "working": 1,
                                                       "done_unseen": 0, "error_unseen": 0,
                                                       "attention": 0}}
        if method == "POST" and path.startswith("/api/jobs/") and path.endswith("/kill"):
            return 200, {"ok": True, "id": int(path.split("/")[3])}
        if (method, path) == ("GET", "/api/approvals/kira"):
            return 200, {"approvals": [{"id": APPR_ID, "n": 1, "instance": "g-1", "engine": "gemini",
                                        "level": "full", "expires_in": 120, "fp16": "a" * 16, "state": "pending",
                                        "prompt": "LỌT PROMPT", "secret": "x"}]}
        if method == "POST" and path.startswith("/api/approvals/") and "/kira/" in path:
            return 200, {"ok": True, "state": path.rsplit("/", 1)[1] + "ed"}
        if (method, path) == ("GET", "/api/ledger/summary"):
            return 200, self.ledger
        return 404, {"detail": "nope"}


@pytest.fixture
def env():
    clock = [1_000_000.0]
    up = Upstream()
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=up, now=lambda: clock[0])
    return TestClient(app), up, clock


def _get(env, path="/kira/status", **over):
    client, _, clock = env
    h = _sign("GET", path, ts=int(clock[0]), nonce=over.pop("nonce", "n-get-1"))
    h.update(over)
    return client.get(path, headers=h)


def _stop(env, body, nonce="n-stop-1"):
    client, _, clock = env
    raw = json.dumps(body).encode()
    h = _sign("POST", "/kira/stop", raw, ts=int(clock[0]), nonce=nonce)
    h["Content-Type"] = "application/json"
    return client.post("/kira/stop", content=raw, headers=h)


# --- allowlist IP (fail-closed) ---------------------------------------------------
def test_empty_allowlist_denies_everything():
    app = kg.create_app(secret=SECRET, allowed_ips=set(), fetch=Upstream(), now=lambda: 1.0)
    r = TestClient(app).get("/kira/status", headers=_sign("GET", "/kira/status", ts=1, nonce="a"))
    assert r.status_code == 403


def test_ip_not_in_allowlist_denied():
    app = kg.create_app(secret=SECRET, allowed_ips={"10.9.9.9"}, fetch=Upstream(), now=lambda: 1.0)
    r = TestClient(app).get("/kira/status", headers=_sign("GET", "/kira/status", ts=1, nonce="a"))
    assert r.status_code == 403


# --- xác thực HMAC ----------------------------------------------------------------
def test_missing_headers_401(env):
    client, up, _ = env
    assert client.get("/kira/status").status_code == 401
    assert up.calls == []


def test_wrong_signature_401(env):
    r = _get(env, **{"X-Kira-Sig": "0" * 64})
    assert r.status_code == 401
    assert env[1].calls == []


def test_wrong_secret_401(env):
    client, up, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]), nonce="x", secret=b"z" * 32)
    assert client.get("/kira/status", headers=h).status_code == 401
    assert up.calls == []


def test_stale_timestamp_401(env):
    client, up, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]) - 31, nonce="old")
    assert client.get("/kira/status", headers=h).status_code == 401
    h = _sign("GET", "/kira/status", ts=int(clock[0]) + 31, nonce="future")
    assert client.get("/kira/status", headers=h).status_code == 401
    assert up.calls == []


def test_non_numeric_timestamp_401(env):
    client, _, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]), nonce="n1")
    h["X-Kira-Ts"] = "abc"
    assert client.get("/kira/status", headers=h).status_code == 401


def test_replay_same_nonce_rejected(env):
    assert _get(env, nonce="dup").status_code == 200
    r = _get(env, nonce="dup")
    assert r.status_code == 401
    assert len(env[1].calls) == 1


def test_signature_bound_to_path(env):
    client, up, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]), nonce="p1")
    assert client.post("/kira/stop", content=b'{"job_id": 7}', headers=h).status_code == 401
    assert up.calls == []


def test_signature_bound_to_body(env):
    client, up, clock = env
    h = _sign("POST", "/kira/stop", b'{"job_id": 1}', ts=int(clock[0]), nonce="b1")
    h["Content-Type"] = "application/json"
    r = client.post("/kira/stop", content=b'{"job_id": 7}', headers=h)
    assert r.status_code == 401
    assert up.calls == []


# --- hành vi đúng -----------------------------------------------------------------
def test_status_returns_only_whitelisted_fields(env):
    r = _get(env)
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["working"] == 1
    job = data["jobs"][0]
    assert set(job) <= {"id", "instance", "engine", "state", "elapsed"}
    assert job["id"] == 7 and job["state"] == "working"
    blob = r.text
    assert "BÍ MẬT" not in blob and "nhạy cảm" not in blob and "4242" not in blob


def test_stop_calls_kill_on_upstream(env):
    r = _stop(env, {"job_id": 7})
    assert r.status_code == 200 and r.json() == {"ok": True, "id": 7}
    assert env[1].calls == [("POST", "/api/jobs/7/kill", None)]


@pytest.mark.parametrize("bad", [{"job_id": "7; rm"}, {"job_id": True}, {"job_id": -1},
                                 {"job_id": 1.5}, {}, {"job_id": 7, "all": True}])
def test_stop_rejects_bad_job_id_without_upstream_call(env, bad):
    r = _stop(env, bad)
    assert r.status_code in (400, 422)
    assert env[1].calls == []


def test_oversized_body_413(env):
    client, up, clock = env
    raw = b'{"job_id": 7, "pad": "' + b"a" * 5000 + b'"}'
    h = _sign("POST", "/kira/stop", raw, ts=int(clock[0]), nonce="big")
    r = client.post("/kira/stop", content=raw, headers=h)
    assert r.status_code == 413
    assert up.calls == []


# --- bề mặt hẹp -------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/bus", "/api/jobs/1/kill", "/api/remote/toggle",
                                  "/docs", "/openapi.json", "/redoc", "/"])
def test_other_routes_not_exposed(env, path):
    client, up, clock = env
    h = _sign("GET", path, ts=int(clock[0]), nonce="x" + path.replace("/", "-"))
    assert client.get(path, headers=h).status_code == 404
    assert client.post(path, headers=h).status_code in (404, 405)
    assert up.calls == []


# --- giới hạn tần suất ------------------------------------------------------------
def test_rate_limit_429():
    clock = [1_000_000.0]
    up = Upstream()
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=up,
                        now=lambda: clock[0], rate_limit=(3, 60))
    c = TestClient(app)
    codes = []
    for i in range(5):
        h = _sign("GET", "/kira/status", ts=int(clock[0]), nonce=f"r{i}")
        codes.append(c.get("/kira/status", headers=h).status_code)
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_rate_limit_counts_failed_auth_too():
    clock = [1_000_000.0]
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=Upstream(),
                        now=lambda: clock[0], rate_limit=(2, 60))
    c = TestClient(app)
    for _ in range(2):
        assert c.get("/kira/status").status_code == 401
    assert c.get("/kira/status").status_code == 429


# --- upstream lỗi không lộ chi tiết -----------------------------------------------
def test_upstream_failure_returns_generic_502():
    def boom(method, path, body=None):
        raise OSError("connect refused: 127.0.0.1:7788 secret-detail")
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=boom, now=lambda: 5.0)
    r = TestClient(app).get("/kira/status", headers=_sign("GET", "/kira/status", ts=5, nonce="u"))
    assert r.status_code == 502
    assert "secret-detail" not in r.text and "7788" not in r.text


# --- bind / secret ----------------------------------------------------------------
@pytest.mark.parametrize("host", ["", "0.0.0.0", "::", "[::]", "0:0:0:0:0:0:0:0", " 0.0.0.0 ", None])
def test_validate_bind_rejects_wildcards(host):
    with pytest.raises(ValueError):
        kg.validate_bind(host)


@pytest.mark.parametrize("host", ["127.0.0.1", "100.101.102.103", "192.168.1.50"])
def test_validate_bind_accepts_specific_ip(host):
    assert kg.validate_bind(host) == host


def test_validate_bind_rejects_hostname():
    with pytest.raises(ValueError):
        kg.validate_bind("localhost")


def test_load_secret_reads_file_and_enforces_length(tmp_path):
    p = tmp_path / "hmac.key"
    p.write_bytes(b"s" * 32 + b"\n")
    assert kg.load_secret(str(p)) == b"s" * 32
    short = tmp_path / "short.key"
    short.write_bytes(b"abc")
    with pytest.raises(ValueError):
        kg.load_secret(str(short))
    with pytest.raises(ValueError):
        kg.load_secret(str(tmp_path / "missing.key"))


def test_parse_allowed_ips():
    assert kg.parse_allowed_ips("10.0.0.5, 100.64.0.1 ,") == {"10.0.0.5", "100.64.0.1"}
    assert kg.parse_allowed_ips("") == set()
    assert kg.parse_allowed_ips(None) == set()


# --- vòng sửa sau security review (RF1–RF7, RF9) ----------------------------------
def test_chunked_oversized_body_413(env):                       # RF1
    client, up, clock = env

    def gen():
        for _ in range(10):
            yield b"a" * 1000
    h = _sign("POST", "/kira/stop", b"", ts=int(clock[0]), nonce="chunk")
    r = client.post("/kira/stop", content=gen(), headers=h)
    assert r.status_code == 413
    assert up.calls == []


def test_non_ascii_header_is_401_not_500(env):                  # RF2
    client, up, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]), nonce="na")
    h["X-Kira-Sig"] = ("é" * 64).encode("latin-1")
    assert client.get("/kira/status", headers=h).status_code == 401
    h2 = _sign("GET", "/kira/status", ts=int(clock[0]), nonce="nb")
    h2["X-Kira-Ts"] = "²".encode("latin-1")
    assert client.get("/kira/status", headers=h2).status_code == 401
    assert up.calls == []


def test_fetch_does_not_follow_redirects():                      # RF4
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:9/x")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, _ = kg._make_fetch(f"http://127.0.0.1:{srv.server_port}")("GET", "/api/jobs")
        assert code == 307
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("url", ["https://127.0.0.1:7788", "http://evil.example", "ftp://127.0.0.1"])
def test_make_fetch_rejects_non_loopback_or_scheme(url):          # RF4
    with pytest.raises(ValueError):
        kg._make_fetch(url)


def test_tin_before_process_start_rejected(env):                # RF5 (replay sau restart)
    client, up, clock = env
    h = _sign("GET", "/kira/status", ts=int(clock[0]) - 5, nonce="pre")
    assert client.get("/kira/status", headers=h).status_code == 401
    assert up.calls == []


def test_non_kira_path_from_unlisted_ip_is_403_not_404():        # RF6
    app = kg.create_app(secret=SECRET, allowed_ips={"10.9.9.9"}, fetch=Upstream(), now=lambda: 1.0)
    assert TestClient(app).get("/anything").status_code == 403


def test_rate_limit_covers_unknown_paths():                      # RF6
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=Upstream(),
                        now=lambda: 1_000_000.0, rate_limit=(2, 60))
    c = TestClient(app)
    assert [c.get("/nope").status_code for _ in range(3)] == [404, 404, 429]


def test_nonce_boundary_replay_rejected():                      # RF7
    clock = [1_000_000.0]
    up = Upstream()
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=up, now=lambda: clock[0])
    c = TestClient(app)
    ts = 1_000_030                                  # tin "từ tương lai" +30 s, vẫn trong cửa sổ
    h = _sign("GET", "/kira/status", ts=ts, nonce="edge")
    assert c.get("/kira/status", headers=h).status_code == 200
    clock[0] = ts + 30                              # đúng ranh giới cửa sổ
    assert c.get("/kira/status", headers=h).status_code == 401


def test_deeply_nested_json_is_422_not_500(env):                # RF9
    client, up, clock = env
    raw = b"[" * 4000
    h = _sign("POST", "/kira/stop", raw, ts=int(clock[0]), nonce="deep")
    assert client.post("/kira/stop", content=raw, headers=h).status_code == 422
    assert up.calls == []


def test_validate_bind_strips_ipv6_brackets():                  # RF9
    assert kg.validate_bind("[::1]") == "::1"


def test_parse_allowed_ips_normalizes_ipv6_and_rejects_garbage():  # RF9
    assert kg.parse_allowed_ips("FE80:0:0:0:0:0:0:0001") == {"fe80::1"}
    with pytest.raises(ValueError):
        kg.parse_allowed_ips("10.0.0.5,not-an-ip")


# --- duyệt: Kira chỉ xem / Từ chối / Hoãn (bước 5, B+) -------------------------------------
def test_kira_approvals_list_whitelists_fields(env):
    r = _get(env, "/kira/approvals", nonce="al1")
    assert r.status_code == 200
    [a] = r.json()["approvals"]
    assert set(a) <= {"id", "n", "instance", "engine", "level", "expires_in", "fp16", "state"}
    assert a["id"] == APPR_ID and "LỌT PROMPT" not in r.text and "secret" not in r.text


def _post(env, path, nonce, body=b""):
    client, _, clock = env
    h = _sign("POST", path, body, ts=int(clock[0]), nonce=nonce)
    return client.post(path, content=body, headers=h)


@pytest.mark.parametrize("action", ["reject", "defer"])
def test_kira_reject_and_defer_call_dedicated_upstream_route(env, action):
    r = _post(env, f"/kira/approvals/{APPR_ID}/{action}", "k-" + action)
    assert r.status_code == 200
    assert env[1].calls == [("POST", f"/api/approvals/{APPR_ID}/kira/{action}", None)]


def test_kira_has_no_approve_route(env):
    for path in (f"/kira/approvals/{APPR_ID}/approve", f"/kira/approvals/{APPR_ID}/decide", "/kira/approve"):
        assert _post(env, path, "x" + str(len(path))).status_code in (404, 405)
    assert env[1].calls == []


@pytest.mark.parametrize("bad", ["../x", "abc", "0123456789ABCDEF" * 2, APPR_ID + "0", "%2e%2e"])
def test_kira_approval_id_is_strictly_validated(env, bad):
    r = _post(env, f"/kira/approvals/{bad}/reject", "bad" + str(abs(hash(bad)) % 9999))
    assert r.status_code in (401, 404, 422)      # 401: đường dẫn mã hoá % lệch chuỗi đã ký
    assert env[1].calls == []


def test_kira_status_summary_includes_pending_approvals_count():
    up = Upstream()
    orig = up.__call__

    def with_appr(method, path, body=None):
        code, data = orig(method, path, body)
        if (method, path) == ("GET", "/api/jobs"):
            data["summary"]["approvals"] = 2
        return code, data
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=with_appr, now=lambda: 1_000_000.0)
    r = TestClient(app).get("/kira/status", headers=_sign("GET", "/kira/status", ts=1_000_000, nonce="s-appr"))
    assert r.json()["summary"]["approvals"] == 2


# --- Giai đoạn 2 (TK2): /kira/info, /kira/ledger, từ chối query -------------------------------------
def test_kira_info_returns_machine_name_only():
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=Upstream(), now=lambda: 1_000_000.0,
                        machine_name="may-2")
    r = TestClient(app).get("/kira/info", headers=_sign("GET", "/kira/info", ts=1_000_000, nonce="i1"))
    assert r.status_code == 200 and r.json() == {"name": "may-2"}


@pytest.mark.parametrize("bad", ["", "a b", "a/b", "x" * 65, "tên-có-dấu", "a\nb", None, 5])
def test_machine_name_is_sanitised(bad):
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=Upstream(), now=lambda: 1_000_000.0,
                        machine_name=bad)
    r = TestClient(app).get("/kira/info", headers=_sign("GET", "/kira/info", ts=1_000_000, nonce="i2"))
    assert r.json() == {"name": "unknown"}


def test_machine_name_default_comes_from_env_then_hostname(monkeypatch):
    monkeypatch.setenv("KIRA_MACHINE_NAME", "tram-a")
    assert kg.default_machine_name() == "tram-a"
    monkeypatch.delenv("KIRA_MACHINE_NAME")
    assert kg.default_machine_name() == kg.sanitize_machine_name(socket_hostname().split(".")[0])
    monkeypatch.setattr(kg.socket, "gethostname", lambda: "may.corp.local")
    assert kg.default_machine_name() == "may"


def socket_hostname():
    import socket
    return socket.gethostname()


def test_kira_ledger_is_whitelisted(env):
    r = _get(env, "/kira/ledger", nonce="l1")
    assert r.status_code == 200
    d = r.json()
    assert d == {"date": "2026-11-13", "engines": {"claude": {"count": 3, "cap": 40, "state": "ok"}},
                 "triggers": {"human_turn": 3}, "outcomes": {"ok": 3}}
    assert "leak" not in r.text and "evil" not in r.text and '"x"' not in r.text


def test_kira_ledger_drops_hostile_values():
    up = Upstream()
    up.ledger = {"date": "<script>", "engines": {"claude": {"count": -1, "cap": 40, "state": "ok"},
                                                 "x" * 40: {"count": 1, "cap": 40, "state": "ok"},
                                                 "codex": {"count": True, "cap": 40, "state": "ok"},
                                                 "gemini": {"count": 2, "cap": 40, "state": "pwn"},
                                                 "agy": {"count": 10 ** 12, "cap": 40, "state": "ok"},
                                                 "ollama": {"count": 2, "cap": 40, "state": "warn"}},
                 "triggers": {"human_turn": "3", "direct": 1.5, "approved": 2}, "outcomes": []}
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=up, now=lambda: 1_000_000.0)
    d = TestClient(app).get("/kira/ledger", headers=_sign("GET", "/kira/ledger", ts=1_000_000, nonce="l2")).json()
    assert d["date"] is None and list(d["engines"]) == ["ollama"] and d["triggers"] == {"approved": 2} and d["outcomes"] == {}


def test_kira_ledger_upstream_failure_is_502():
    def boom(method, path, body=None):
        raise OSError("down")
    app = kg.create_app(secret=SECRET, allowed_ips={CLIENT_IP}, fetch=boom, now=lambda: 1_000_000.0)
    r = TestClient(app).get("/kira/ledger", headers=_sign("GET", "/kira/ledger", ts=1_000_000, nonce="l3"))
    assert r.status_code == 502


@pytest.mark.parametrize("path", ["/kira/status", "/kira/info", "/kira/ledger", "/kira/approvals"])
def test_query_strings_are_refused_on_every_route(env, path):
    client, up, clock = env
    h = _sign("GET", path, ts=int(clock[0]), nonce="q" + path.rsplit("/", 1)[1])
    assert client.get(path + "?x=1", headers=h).status_code == 422
    assert up.calls == []


def test_query_strings_are_refused_on_post_routes_too(env):
    client, up, clock = env
    raw = json.dumps({"job_id": 7}).encode()
    h = _sign("POST", "/kira/stop", raw, ts=int(clock[0]), nonce="qp1")
    assert client.post("/kira/stop?x=1", content=raw, headers=h).status_code == 422
    h2 = _sign("POST", f"/kira/approvals/{APPR_ID}/reject", b"", ts=int(clock[0]), nonce="qp2")
    assert client.post(f"/kira/approvals/{APPR_ID}/reject?x=1", content=b"", headers=h2).status_code == 422
    assert up.calls == []
