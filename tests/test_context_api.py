import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(upload_dir))
    import importlib
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_scan_context(client, tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET", encoding="utf-8")
    r = client.post("/api/context/scan", json={"path": str(tmp_path)})
    assert r.status_code == 200
    names = [f["path"].replace("\\", "/").split("/")[-1] for f in r.json()]
    assert "a.py" in names and ".env" not in names


def test_upload_context(client):
    r = client.post(
        "/api/context/upload",
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["path"].endswith("note.txt")
    assert os.path.exists(body["path"])


def test_attach_context(client, tmp_path):
    client.post("/api/instances", json={"agent_name": "coder", "engine": "codex", "voice": "v"})
    p = tmp_path / "f.py"
    p.write_text("print(1)", encoding="utf-8")
    r = client.post("/api/context/attach", json={"instance": "coder-1", "path": str(p)})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "inline"
    assert "print(1)" in body["content"]


def test_attach_unknown_instance_404(client, tmp_path):
    p = tmp_path / "f.py"
    p.write_text("x", encoding="utf-8")
    r = client.post("/api/context/attach", json={"instance": "nope", "path": str(p)})
    assert r.status_code == 404
