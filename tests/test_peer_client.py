"""TK1 (Giai đoạn 2 đa máy): client ký HMAC sang cổng Kira của máy phụ. Chặn SSRF, bảng trắng sáu đường, khoá riêng
từng máy, lọc phản hồi không tin cậy. Mọi kết nối là giả hoặc loopback; KHÔNG đọc kho secret thật, KHÔNG ra ngoài loopback."""
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time

import pytest

from server import kira_gateway as kg
from server import peer_client as pc

KEY = ("ab12" * 16).encode()                 # 64 ký tự hex
APPR = "0123456789abcdef" * 2


@pytest.fixture(autouse=True)
def _no_external_connect(monkeypatch):
    """SC7: không kết nối tới bất kỳ địa chỉ nào ngoài loopback trong test."""
    orig = socket.socket.connect

    def guarded(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        assert str(host).startswith("127.") or str(host) == "::1", f"kết nối ra ngoài loopback: {host}"
        return orig(self, addr)
    monkeypatch.setattr(socket.socket, "connect", guarded)


# ------------------------------------------------------------------ URL ---------------------
@pytest.mark.parametrize("url", ["http://100.64.0.5:7790", "http://100.127.255.254:7790", "http://10.1.2.3:8000",
                                 "http://172.16.0.9:7790", "http://172.31.255.1:7790", "http://192.168.1.50:7790",
                                 "http://[fd12:3456::1]:7790"])
def test_valid_private_urls_accepted(url):
    ip, port = pc.parse_peer_url(url)
    assert port == int(url.rsplit(":", 1)[1])


@pytest.mark.parametrize("url", [
    "http://8.8.8.8:7790", "http://1.1.1.1:7790", "http://100.128.0.1:7790", "http://172.32.0.1:7790",
    "http://example.com:7790", "http://localhost:7790", "http://100.64.0.5.nip.io:7790",
    "https://100.64.0.5:7790", "HTTP://100.64.0.5:7790", "ftp://100.64.0.5:7790",
    "http://user@100.64.0.5:7790", "http://100.64.0.5:7790/", "http://100.64.0.5:7790/x",
    "http://100.64.0.5:7790?a=1", "http://100.64.0.5:7790#f", "http://100.64.0.5", "http://100.64.0.5:80",
    "http://100.64.0.5:1023", "http://100.64.0.5:65536", "http://100.64.0.5:07790x",
    "http://[::ffff:100.64.0.5]:7790", "http://[::ffff:8.8.8.8]:7790", "http://[fe80::1%eth0]:7790",
    "http://[fe80::1]:7790", "http://169.254.169.254:7790", "http://0.0.0.0:7790", "http://224.0.0.1:7790",
    "http://[ff02::1]:7790", "http://2130706433:7790", "http://0x7f.0.0.1:7790", "http://0177.0.0.1:7790",
    "http://100.64.5:7790", "http://100.064.0.5:7790", " http://100.64.0.5:7790", "http://100.64.0.5:7790 ",
    "http://100.64.0.5:7790\n", "http://100.64.0.5:7790\r\nHost: evil", "http://100.64.0.5\x00:7790",
    "http://１００.64.0.5:7790", "", None, 7790, b"http://100.64.0.5:7790"])
def test_invalid_urls_rejected(url):
    with pytest.raises(pc.PeerError) as e:
        pc.parse_peer_url(url)
    assert e.value.code == "bad_url"


def test_loopback_only_when_explicitly_allowed():
    with pytest.raises(pc.PeerError):
        pc.parse_peer_url("http://127.0.0.1:7790")
    with pytest.raises(pc.PeerError):
        pc.parse_peer_url("http://[::1]:7790")
    assert pc.parse_peer_url("http://127.0.0.1:7790", allow_loopback=True)[1] == 7790


def test_peer_pointing_at_hub_own_port_rejected():
    with pytest.raises(pc.PeerError):
        pc.parse_peer_url("http://127.0.0.1:7788", allow_loopback=True, own_ports=(7788,))
    with pytest.raises(pc.PeerError):
        pc.parse_peer_url("http://100.64.0.5:7788", own_ports=(7788,))


# ------------------------------------------------------------------ khoá --------------------
def _write_key(d, name, content=KEY):
    (d / f"{name}.key").write_bytes(content)


def test_load_peer_key_reads_same_bytes_as_gateway(tmp_path):
    _write_key(tmp_path, "may-2", KEY + b"\n")
    got = pc.load_peer_key("may-2", key_dir=str(tmp_path))
    assert got == KEY == kg.load_secret(str(tmp_path / "may-2.key"))


@pytest.mark.parametrize("content", [b"", b"abc", b"ab12" * 300, b"\xff" * 80, (b"ab12" * 16) + b" x", b"has space inside the key value 1234567890abcdef"])
def test_bad_key_content_rejected_without_leaking(tmp_path, content):
    _write_key(tmp_path, "may-2", content)
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_key("may-2", key_dir=str(tmp_path))
    assert e.value.code == "no_key"
    assert str(tmp_path) not in str(e.value) and "ab12" not in str(e.value)


def test_base64url_key_accepted(tmp_path):
    k = (b"Ab_-" * 11)[:44]
    _write_key(tmp_path, "may-3", k)
    assert pc.load_peer_key("may-3", key_dir=str(tmp_path)) == k


@pytest.mark.parametrize("name", ["", "A", "../x", "a/b", "a\\b", "a.b", "x" * 33, "a b", "a\x00b", None, 5])
def test_peer_name_must_match_pattern(tmp_path, name):
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_key(name, key_dir=str(tmp_path))
    assert e.value.code in ("bad_name", "no_key")


def test_missing_key_file(tmp_path):
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_key("may-9", key_dir=str(tmp_path))
    assert e.value.code == "no_key"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink cần quyền đặc biệt trên Windows")
def test_symlinked_key_rejected(tmp_path):
    other = tmp_path / "other.key"
    other.write_bytes(KEY)
    d = tmp_path / "keys"
    d.mkdir()
    os.symlink(other, d / "may-2.key")
    with pytest.raises(pc.PeerError):
        pc.load_peer_key("may-2", key_dir=str(d))


def test_key_dir_not_taken_from_config_only_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_PEER_KEY_DIR", str(tmp_path))
    _write_key(tmp_path, "may-2")
    assert pc.load_peer_key("may-2") == KEY


def test_pin_must_match_exactly(tmp_path):
    (tmp_path / "may-2.url").write_text("http://100.64.0.5:7790\n", encoding="utf-8")
    assert pc.load_peer_pin("may-2", key_dir=str(tmp_path)) == "http://100.64.0.5:7790"
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_pin("may-3", key_dir=str(tmp_path))
    assert e.value.code == "no_pin"


def test_make_client_requires_pin_and_matching_url(tmp_path):
    _write_key(tmp_path, "may-2")
    with pytest.raises(pc.PeerError) as e:
        pc.make_client("may-2", "http://100.64.0.5:7790", key_dir=str(tmp_path))
    assert e.value.code == "no_pin"
    (tmp_path / "may-2.url").write_text("http://100.64.0.5:7790", encoding="utf-8")
    pc.make_client("may-2", "http://100.64.0.5:7790", key_dir=str(tmp_path))
    with pytest.raises(pc.PeerError) as e:
        pc.make_client("may-2", "http://100.64.0.6:7790", key_dir=str(tmp_path))
    assert e.value.code == "pin_mismatch"


def test_key_fingerprint_is_not_the_key():
    fp = pc.key_fingerprint(KEY)
    assert fp != KEY.decode() and len(fp) == 64 and fp == hashlib.sha256(KEY).hexdigest()


# ------------------------------------------------------------------ kết nối giả --------------
class FakeResp:
    def __init__(self, status=200, body=b"{}", chunks=None, clock=None, step=0.0):
        self.status, self._chunks, self._clock, self._step = status, list(chunks) if chunks else [body], clock, step

    def read(self, n=-1):
        if self._clock is not None:
            self._clock[0] += self._step
        return self._chunks.pop(0) if self._chunks else b""


class FakeConn:
    log: list = []

    def __init__(self, ip, port, timeout, resp=None, exc=None):
        self.ip, self.port, self.timeout, self._resp, self._exc = ip, port, timeout, resp, exc
        self.sent = None
        FakeConn.log.append(self)

    def request(self, method, path, body=None, headers=None):
        self.sent = (method, path, body, dict(headers or {}))

    def getresponse(self):
        if self._exc:
            raise self._exc
        return self._resp

    def close(self):
        pass


def client(resp=None, exc=None, clock=None, **kw):
    FakeConn.log = []

    def connect(ip, port, timeout):
        return FakeConn(ip, port, timeout, resp=resp() if callable(resp) else resp, exc=exc)
    kw.setdefault("now", lambda: 1_700_000_000.0)
    return pc.PeerClient("may-2", "http://100.64.0.5:7790", KEY, connect=connect, **({"mono": (lambda: clock[0])} if clock else {}), **kw)


def _sig(method, path, body, ts, nonce, key=KEY):
    return hmac.new(key, f"{method}\n{path}\n{ts}\n{nonce}\n".encode() + body, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ bảng trắng -----------------
GOOD = [("GET", "/kira/status", None), ("GET", "/kira/info", None), ("GET", "/kira/ledger", None),
        ("GET", "/kira/approvals", None), ("POST", "/kira/stop", {"job_id": 7}),
        ("POST", f"/kira/approvals/{APPR}/reject", None), ("POST", f"/kira/approvals/{APPR}/defer", None)]


@pytest.mark.parametrize("method,path,body", GOOD)
def test_whitelisted_routes_are_signed_and_sent(method, path, body):
    c = client(FakeResp(200, b'{"ok": true}'))
    status, data = c.request(method, path, body)
    assert status == 200 and data == {"ok": True}
    [conn] = FakeConn.log
    m, p, sent_body, h = conn.sent
    assert (m, p) == (method, path) and conn.ip == pc.parse_peer_url("http://100.64.0.5:7790")[0] and conn.port == 7790
    raw = sent_body or b""
    assert h["X-Kira-Sig"] == _sig(method, path, raw, h["X-Kira-Ts"], h["X-Kira-Nonce"])     # ký ĐÚNG chuỗi byte đã gửi
    if body is not None:
        assert json.loads(raw) == body


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/jobs", None), ("GET", "/api/bus", None), ("POST", "/api/jobs/1/kill", None), ("GET", "/kira/stop", None),
    ("POST", "/kira/status", None), ("GET", "/kira/status?x=1", None), ("GET", "/kira/status#f", None),
    ("GET", "/kira/status/", None), ("GET", "/KIRA/status", None), ("GET", "kira/status", None),
    ("GET", "/kira/approvals/ABC/reject", None), ("POST", f"/kira/approvals/{APPR.upper()}/reject", None),
    ("POST", f"/kira/approvals/{APPR}/approve", None), ("POST", f"/kira/approvals/{APPR}/reject/", None),
    ("POST", f"/kira/approvals/{APPR}0/reject", None), ("POST", "/kira/approvals/../reject", None),
    ("POST", "/kira/stop", {"job_id": 0}), ("POST", "/kira/stop", {"job_id": 2 ** 31}), ("POST", "/kira/stop", {"job_id": True}),
    ("POST", "/kira/stop", {"job_id": "7"}), ("POST", "/kira/stop", {"job_id": 7, "all": True}), ("POST", "/kira/stop", {}),
    ("POST", "/kira/stop", None), ("POST", f"/kira/approvals/{APPR}/reject", {"x": 1}), ("GET", "/kira/status", {"x": 1}),
    ("DELETE", "/kira/status", None), ("PUT", "/kira/stop", {"job_id": 1}), ("GET", "/kira/status\r\nX: y", None),
    ("GET", None, None), (None, "/kira/status", None)])
def test_everything_else_is_refused_before_any_connection(method, path, body):
    c = client(FakeResp())
    with pytest.raises(pc.PeerError) as e:
        c.request(method, path, body)
    assert e.value.code == "bad_request"
    assert FakeConn.log == []                       # không mở kết nối nào


def test_nonce_is_unique_and_url_revalidated_each_call(monkeypatch):
    c = client(lambda: FakeResp(200, b"{}"))
    c.request("GET", "/kira/status")
    c.request("GET", "/kira/status")
    n = [x.sent[3]["X-Kira-Nonce"] for x in FakeConn.log]
    assert len(set(n)) == 2
    c._url = "http://8.8.8.8:7790"                  # giả lập URL bị đổi giữa chừng
    with pytest.raises(pc.PeerError) as e:
        c.request("GET", "/kira/status")
    assert e.value.code == "bad_url" and len(FakeConn.log) == 2


# ------------------------------------------------------------------ phản hồi không tin cậy -----
@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (403, "forbidden"), (404, "not_found"), (409, "not_pending"),
                                         (422, "invalid"), (429, "rate_limited"), (502, "upstream_unavailable"),
                                         (301, "bad_response"), (307, "bad_response"), (500, "bad_response"), (204, "bad_response")])
def test_status_codes_map_to_short_codes(status, code):
    with pytest.raises(pc.PeerError) as e:
        client(FakeResp(status, b'{"detail":"x"}')).request("GET", "/kira/status")
    assert e.value.code == code


@pytest.mark.parametrize("body", [b"", b"not json", b"[1,2,3]", b'"str"', b"123", b"null", b'{"a": NaN}', b'{"a": Infinity}',
                                  b'{"a": -Infinity}', b"\xff\xfe\x00", b"[" * 5000, b'{"a":' * 3000 + b"1" + b"}" * 3000,
                                  b'{"n": ' + b"9" * 5000 + b"}", b'{"a": 1} trailing'])
def test_malicious_or_malformed_bodies_become_bad_response(body):
    with pytest.raises(pc.PeerError) as e:
        client(FakeResp(200, body)).request("GET", "/kira/status")
    assert e.value.code == "bad_response"


def test_oversized_response_rejected():
    big = b'{"x": "' + b"a" * (pc.MAX_BYTES + 10) + b'"}'
    with pytest.raises(pc.PeerError) as e:
        client(FakeResp(200, chunks=[big[i:i + 4096] for i in range(0, len(big), 4096)])).request("GET", "/kira/status")
    assert e.value.code == "bad_response"


def test_trickling_peer_hits_total_deadline():
    clock = [0.0]
    r = FakeResp(200, chunks=[b"x"] * 1000, clock=clock, step=3.0)
    c = client(r, clock=clock, deadline=6.0)
    with pytest.raises(pc.PeerError) as e:
        c.request("GET", "/kira/status")
    assert e.value.code == "timeout" and clock[0] <= 6.0 + 3.0 * 2


def test_socket_errors_become_generic_codes():
    for exc, code in [(socket.timeout("t"), "timeout"), (ConnectionRefusedError("100.64.0.5:7790 refused secret"), "unreachable"),
                      (OSError("boom"), "unreachable"), (ValueError("x"), "unreachable")]:
        with pytest.raises(pc.PeerError) as e:
            client(exc=exc).request("GET", "/kira/status")
        assert e.value.code == code
        assert "100.64" not in str(e.value) and "secret" not in str(e.value)


def test_errors_never_contain_url_or_key(caplog):
    caplog.set_level("DEBUG")
    for resp in (FakeResp(401), FakeResp(200, b"junk")):
        with pytest.raises(pc.PeerError) as e:
            client(resp).request("GET", "/kira/status")
        assert "100.64.0.5" not in repr(e.value) and KEY.decode() not in repr(e.value)
    assert "100.64.0.5" not in caplog.text and KEY.decode() not in caplog.text


# ------------------------------------------------------------------ gateway thật trên loopback --------
@pytest.fixture
def live_gateway():
    import uvicorn

    class Up:
        def __call__(self, method, path, body=None):
            if (method, path) == ("GET", "/api/jobs"):
                return 200, {"jobs": [{"id": 3, "instance": "c-1", "engine": "codex", "state": "working", "elapsed": 1.5}],
                             "summary": {"working": 1, "attention": 0}}
            if method == "POST" and path.endswith("/kill"):
                return 200, {"ok": True}
            return 404, {}
    app = kg.create_app(secret=KEY, allowed_ips={"127.0.0.1"}, fetch=Up())
    s = socket.socket()
    s.bind(("127.0.0.1", 0))                           # giữ nguyên socket đã bind: không có khe đua cổng
    s.listen(16)
    port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", proxy_headers=False))
    t = threading.Thread(target=lambda: server.run(sockets=[s]), daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield port
    server.should_exit = True
    t.join(5)
    if t.is_alive():
        server.force_exit = True
        t.join(2)
    s.close()


def test_signed_request_accepted_by_real_gateway(live_gateway):
    c = pc.PeerClient("may-2", f"http://127.0.0.1:{live_gateway}", KEY, allow_loopback=True, own_ports=(7788,))
    status, data = c.request("GET", "/kira/status")
    assert status == 200 and data["jobs"][0]["id"] == 3
    assert c.request("POST", "/kira/stop", {"job_id": 3})[1] == {"ok": True, "id": 3}


def test_wrong_key_and_clock_skew_rejected_by_real_gateway(live_gateway):
    url = f"http://127.0.0.1:{live_gateway}"
    with pytest.raises(pc.PeerError) as e:
        pc.PeerClient("may-2", url, b"z" * 64, allow_loopback=True).request("GET", "/kira/status")
    assert e.value.code == "unauthorized"
    with pytest.raises(pc.PeerError) as e2:
        pc.PeerClient("may-2", url, KEY, allow_loopback=True, now=lambda: time.time() - 200).request("GET", "/kira/status")
    assert e2.value.code == "unauthorized"


def test_key_of_machine_a_does_not_open_machine_b(live_gateway):
    other = b"cd34" * 16
    with pytest.raises(pc.PeerError) as e:
        pc.PeerClient("may-3", f"http://127.0.0.1:{live_gateway}", other, allow_loopback=True).request("GET", "/kira/status")
    assert e.value.code == "unauthorized"


# ------------------------------------------------------------------ sau review TK1 (Opus) ------------------
def _trickle_server(first: bytes, per_byte: float, total_len: int = 4096):
    """Máy phụ độc hại trên loopback: nhận yêu cầu rồi nhả `first` từng byte cách nhau `per_byte` giây."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    stop = threading.Event()

    def run():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            try:
                conn.settimeout(2)
                conn.recv(65536)
                for b in first:
                    if stop.is_set():
                        break
                    conn.sendall(bytes([b]))
                    time.sleep(per_byte)
            except OSError:
                pass
            finally:
                conn.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return srv, srv.getsockname()[1], stop, t


@pytest.mark.parametrize("payload", [
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Pad: " + b"a" * 200 + b"\r\n\r\n{}",                       # nhỏ giọt phần HEADER
    b"HTTP/1.1 200 OK\r\nContent-Length: 4000\r\nContent-Type: application/json\r\n\r\n" + b'{"a":"' + b"b" * 3900])  # nhỏ giọt phần THÂN
def test_real_trickling_peer_is_cut_at_total_deadline(payload):
    srv, port, stop, t = _trickle_server(payload, per_byte=0.1)
    try:
        c = pc.PeerClient("may-2", f"http://127.0.0.1:{port}", KEY, allow_loopback=True, timeout=4.0, deadline=1.0)
        t0 = time.monotonic()
        with pytest.raises(pc.PeerError) as e:
            c.request("GET", "/kira/status")
        elapsed = time.monotonic() - t0
        assert e.value.code == "timeout"
        assert elapsed < 2.5, f"hạn chót tổng 1 s nhưng chặn {elapsed:.2f}s"
    finally:
        stop.set()
        srv.close()
        t.join(3)


def test_errors_carry_no_context_from_underlying_exceptions(tmp_path):
    cases = []
    try:
        pc.load_peer_key("may-9", key_dir=str(tmp_path))
    except pc.PeerError as e:
        cases.append(e)
    try:
        client(exc=ConnectionRefusedError("100.64.0.5:7790")).request("GET", "/kira/status")
    except pc.PeerError as e:
        cases.append(e)
    try:
        client(FakeResp(200, b"{bad")).request("GET", "/kira/status")
    except pc.PeerError as e:
        cases.append(e)
    try:
        pc.parse_peer_url("http://100.64.0.999:7790")
    except pc.PeerError as e:
        cases.append(e)
    assert len(cases) == 4
    for e in cases:
        assert e.__context__ is None and e.__cause__ is None


@pytest.mark.parametrize("body", [b'{"a": 1e400}', b'{"a": -1e999}', b'{"a": 1, "a": 2}', b'{"k": {"x": 1, "x": 1}}'])
def test_overflowing_numbers_and_duplicate_keys_rejected(body):
    with pytest.raises(pc.PeerError) as e:
        client(FakeResp(200, body)).request("GET", "/kira/status")
    assert e.value.code == "bad_response"


def test_key_regex_has_upper_bound(tmp_path):
    _write_key(tmp_path, "may-2", b"a" * 1025)                      # 1025 > MAX_KEY_FILE
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_key("may-2", key_dir=str(tmp_path))
    assert e.value.code == "no_key"


@pytest.mark.skipif(sys.platform != "win32", reason="junction/reparse point chỉ có trên Windows")
def test_junction_named_like_a_key_is_rejected(tmp_path):
    import subprocess
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "may-2.key"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("không tạo được junction")
    with pytest.raises(pc.PeerError) as e:
        pc.load_peer_key("may-2", key_dir=str(tmp_path))
    assert e.value.code == "no_key"
