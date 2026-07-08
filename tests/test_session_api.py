import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setenv("AGENT_CONSOLE_SESSIONS_DIR", str(sessions_dir))
    import importlib
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_create_list_rename_resume_session(client):
    r = client.post("/api/sessions", json={"name": "họp sáng"})
    assert r.status_code == 200
    sid = r.json()["id"]

    r2 = client.get("/api/sessions")
    assert r2.status_code == 200
    assert any(s["id"] == sid and s["name"] == "họp sáng" for s in r2.json())

    r3 = client.patch(f"/api/sessions/{sid}", json={"name": "họp chiều"})
    assert r3.status_code == 200

    r4 = client.get("/api/sessions")
    assert any(s["id"] == sid and s["name"] == "họp chiều" for s in r4.json())

    r5 = client.post(f"/api/sessions/{sid}/resume")
    assert r5.status_code == 200
    assert r5.json()["id"] == sid
    assert r5.json()["turns"] == []


def test_rename_unknown_session_404(client):
    r = client.patch("/api/sessions/doesnotexist", json={"name": "x"})
    assert r.status_code == 404


def test_resume_unknown_session_404(client):
    r = client.post("/api/sessions/doesnotexist/resume")
    assert r.status_code == 404


def test_remote_toggle_success(client, monkeypatch):
    import server.app as app_module

    class FakeResult:
        returncode = 0
        stdout = "remote-control on"
        stderr = ""

    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **k: FakeResult())
    r = client.post("/api/remote/toggle", json={"on": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["requested"] == "on"
    assert "manual_hint" in body


def test_remote_toggle_missing_cli_falls_back(client, monkeypatch):
    import server.app as app_module

    def boom(*a, **k):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(app_module.subprocess, "run", boom)
    r = client.post("/api/remote/toggle", json={"on": False})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["requested"] == "off"
    assert "manual_hint" in body
