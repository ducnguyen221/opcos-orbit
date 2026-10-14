"""Bảo mật API: chặn nâng quyền qua API, allowlist đường dẫn, cổng remote, Host/Origin, cmd /c.
MỌI test mock subprocess/engine — không spawn tiến trình thật."""
import importlib
import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _make(tmp_path, monkeypatch, instances, extra_roots=None):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": instances, "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_CONSOLE_ALLOWED_ROOTS", str(extra_roots or ""))
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app), app_module, cfg


INST = [{"name": "lead-1", "engine": "claude", "role": "Lead", "autonomy": "suggest"},
        {"name": "c-1", "engine": "codex", "role": "Coder", "autonomy": "full"}]


# (1) nâng quyền
def test_api_cannot_raise_autonomy(tmp_path, monkeypatch):
    client, _, cfg = _make(tmp_path, monkeypatch, INST)
    r = client.post("/api/instances/lead-1/update", json={"autonomy": "full"})
    assert r.status_code == 403
    r = client.post("/api/instances/lead-1/update", json={"autonomy": "auto-safe"})
    assert r.status_code == 403
    assert json.loads(cfg.read_text())["instances"][0]["autonomy"] == "suggest"


def test_api_can_lower_or_keep_autonomy(tmp_path, monkeypatch):
    client, _, cfg = _make(tmp_path, monkeypatch, INST)
    assert client.post("/api/instances/c-1/update", json={"autonomy": "auto-safe"}).status_code == 200
    assert client.post("/api/instances/c-1/update", json={"autonomy": "auto-safe"}).status_code == 200
    assert json.loads(cfg.read_text())["instances"][1]["autonomy"] == "auto-safe"


def test_api_rejects_unknown_autonomy_value(tmp_path, monkeypatch):
    client, _, _ = _make(tmp_path, monkeypatch, INST)
    assert client.post("/api/instances/c-1/update", json={"autonomy": "root"}).status_code == 400


def test_api_other_fields_still_updatable(tmp_path, monkeypatch):
    client, _, _ = _make(tmp_path, monkeypatch, INST)
    assert client.post("/api/instances/c-1/update", json={"model": "m"}).status_code == 200


# (2) allowlist đường dẫn
def test_scan_and_attach_reject_outside_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "ok"; allowed.mkdir()
    (allowed / "a.txt").write_text("x")
    outside = tmp_path / "out"; outside.mkdir()
    (outside / "b.txt").write_text("y")
    client, _, _ = _make(tmp_path, monkeypatch, INST, extra_roots=allowed)
    assert client.post("/api/context/scan", json={"path": str(allowed)}).status_code == 200
    assert client.post("/api/context/scan", json={"path": str(outside)}).status_code == 403
    assert client.post("/api/context/attach",
                       json={"instance": "c-1", "path": str(outside / "b.txt")}).status_code == 403
    assert client.post("/api/context/attach",
                       json={"instance": "c-1", "path": str(allowed / "a.txt")}).status_code == 200


def test_dotdot_escape_rejected(tmp_path, monkeypatch):
    allowed = tmp_path / "ok"; allowed.mkdir()
    (tmp_path / "secret.txt").write_text("s")
    client, _, _ = _make(tmp_path, monkeypatch, INST, extra_roots=allowed)
    p = str(allowed / ".." / "secret.txt")
    assert client.post("/api/context/attach", json={"instance": "c-1", "path": p}).status_code == 403


def test_symlink_escape_rejected(tmp_path, monkeypatch):
    allowed = tmp_path / "ok"; allowed.mkdir()
    out = tmp_path / "out"; out.mkdir(); (out / "s.txt").write_text("s")
    link = allowed / "link"
    try:
        os.symlink(out, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("không tạo được symlink")
    client, _, _ = _make(tmp_path, monkeypatch, INST, extra_roots=allowed)
    assert client.post("/api/context/attach",
                       json={"instance": "c-1", "path": str(link / "s.txt")}).status_code == 403


def test_audio_only_serves_tts_output(tmp_path, monkeypatch):
    import tempfile
    secret = tmp_path / "notes.txt"; secret.write_text("s")
    client, _, _ = _make(tmp_path, monkeypatch, INST)
    assert client.get("/audio", params={"p": str(secret)}).status_code == 403
    assert client.get("/audio", params={"p": __file__}).status_code == 403
    good = os.path.join(tempfile.gettempdir(), "ac_test_security.wav")
    open(good, "wb").write(b"RIFF")
    try:
        assert client.get("/audio", params={"p": good}).status_code == 200
    finally:
        os.remove(good)


# (3) remote toggle qua cổng
def test_remote_toggle_denied_when_lead_not_full(tmp_path, monkeypatch):
    client, app_module, _ = _make(tmp_path, monkeypatch, INST)
    with patch.object(app_module.subprocess, "run") as run:
        r = client.post("/api/remote/toggle", json={"on": True})
    assert r.status_code == 403
    run.assert_not_called()


def test_remote_toggle_allowed_when_lead_full(tmp_path, monkeypatch):
    inst = [dict(INST[0], autonomy="full")]
    client, app_module, _ = _make(tmp_path, monkeypatch, inst)

    class R:
        returncode = 0; stdout = "ok"; stderr = ""

    with patch.object(app_module.subprocess, "run", return_value=R()) as run:
        r = client.post("/api/remote/toggle", json={"on": True})
    assert r.status_code == 200 and run.called


# Host / Origin / websocket
def test_foreign_host_and_origin_rejected(tmp_path, monkeypatch):
    client, _, _ = _make(tmp_path, monkeypatch, INST)
    assert client.get("/api/jobs", headers={"Host": "evil.example.com"}).status_code == 403
    assert client.get("/api/jobs", headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.get("/api/jobs", headers={"Host": "localhost:7788",
                                            "Origin": "http://localhost:7788"}).status_code == 200
    assert client.get("/api/jobs", headers={"Host": "127.0.0.1:7788"}).status_code == 200


def test_websocket_foreign_origin_rejected(tmp_path, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    client, _, _ = _make(tmp_path, monkeypatch, INST)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "https://evil.example.com"}):
            pass


# cmd /c
def test_resolve_prefers_ps1_over_cmd_shim(tmp_path):
    from server.adapters import _resolve
    (tmp_path / "claude.cmd").write_text(""); (tmp_path / "claude.ps1").write_text("")
    with patch("server.adapters.shutil.which", return_value=str(tmp_path / "claude.cmd")):
        r = _resolve("claude")
    assert r[0] == "powershell" and r[-1].endswith("claude.ps1")


def test_cmd_shim_rejects_metacharacters_without_spawn(monkeypatch):
    from server import adapters
    from server.config import Instance
    monkeypatch.setattr(adapters, "_resolve", lambda n: ["cmd", "/c", r"C:\x\claude.cmd"])
    with patch("server.adapters.subprocess.Popen") as popen:
        out = adapters.run_agent(Instance(name="c", engine="claude", role="Lead"),
                                 'x" & calc & "', timeout=5)
    assert out.startswith("[ERROR]")
    popen.assert_not_called()
