"""Bước 6b: trạng thái OpenMausBot cho thẻ trong Orbit. Chỉ hỏi 127.0.0.1, chỉ nhận app=openmausbot,
không lộ trường nào khác của /api/health. Không khởi động OpenMausBot thật."""
import http.server
import importlib
import json
import threading

import pytest
from fastapi.testclient import TestClient

from server import maus


def test_status_running_exposes_only_url_and_port():
    st = maus.status(8799, fetch=lambda port: (200, {"app": "openmausbot", "pid": 4242, "box": "off",
                                                    "capabilities": {"x": 1}}))
    assert st == {"running": True, "url": "http://127.0.0.1:8799", "port": 8799}


@pytest.mark.parametrize("resp", [(200, {"app": "something-else"}), (500, {"app": "openmausbot"}),
                                  (200, {}), (200, "html"), (404, {})])
def test_status_not_running_when_response_is_not_openmausbot(resp):
    st = maus.status(8799, fetch=lambda port: resp)
    assert st["running"] is False and st["port"] == 8799


def test_status_survives_fetch_errors():
    def boom(port):
        raise OSError("refused 127.0.0.1:8799 secret-detail")
    st = maus.status(8799, fetch=boom)
    assert st["running"] is False and "secret-detail" not in json.dumps(st)


@pytest.mark.parametrize("bad", ["", "abc", "0", "80", "70000", "-1", "8799; rm", None])
def test_port_from_env_falls_back_to_default_when_invalid(monkeypatch, bad):
    if bad is None:
        monkeypatch.delenv("ORBIT_MAUS_PORT", raising=False)
    else:
        monkeypatch.setenv("ORBIT_MAUS_PORT", bad)
    assert maus.maus_port() == maus.DEFAULT_PORT


def test_port_from_env_accepts_valid(monkeypatch):
    monkeypatch.setenv("ORBIT_MAUS_PORT", "8899")
    assert maus.maus_port() == 8899


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_real_fetch_reads_health_from_loopback():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"app": "openmausbot"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = _serve(H)
    try:
        assert maus.status(srv.server_port)["running"] is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_real_fetch_does_not_follow_redirects():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:9/x")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = _serve(H)
    try:
        assert maus.status(srv.server_port)["running"] is False
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_status_route_never_starts_anything(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    import server.app as app_module
    importlib.reload(app_module)
    monkeypatch.setattr(maus, "fetch_health", lambda port, timeout=1.5: (200, {"app": "openmausbot", "pid": 1}))
    c = TestClient(app_module.app)
    d = c.get("/api/maus/status").json()
    assert d["running"] is True and d["url"].startswith("http://127.0.0.1:") and "pid" not in d
    for path in ("/api/maus/start", "/api/maus/stop"):          # không có API khởi động/tắt (agent gọi được!)
        assert c.post(path).status_code in (404, 405)
    assert c.get("/api/maus/status", headers={"Host": "evil.example"}).status_code == 403
