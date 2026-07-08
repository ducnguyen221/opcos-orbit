import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    # reload module fresh so it picks up the env var config path
    import importlib
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_get_agents_returns_list(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_and_rename_instance(client):
    r = client.post("/api/instances", json={"agent_name": "front-end-dev", "engine": "codex", "voice": "voice-b"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "front-end-dev-1"

    r2 = client.get("/api/instances")
    assert r2.status_code == 200
    assert any(i["name"] == "front-end-dev-1" for i in r2.json())

    r3 = client.patch("/api/instances/front-end-dev-1", json={"new_name": "fe-lead"})
    assert r3.status_code == 200

    r4 = client.get("/api/instances")
    assert any(i["name"] == "fe-lead" for i in r4.json())


def test_delete_instance(client):
    client.post("/api/instances", json={"agent_name": "researcher", "engine": "gemini", "voice": "voice-c"})
    r = client.delete("/api/instances/researcher-1")
    assert r.status_code == 200
    r2 = client.get("/api/instances")
    assert not any(i["name"] == "researcher-1" for i in r2.json())


def test_update_instance_engine_and_role(client):
    client.post("/api/instances", json={"agent_name": "researcher", "engine": "gemini", "voice": "v"})
    r = client.post("/api/instances/researcher-1/update",
                    json={"engine": "agy", "role": "Lead", "model": "qwen2.5:7b"})
    assert r.status_code == 200
    got = {i["name"]: i for i in client.get("/api/instances").json()}
    assert got["researcher-1"]["engine"] == "agy"
    assert got["researcher-1"]["role"] == "Lead"
    assert got["researcher-1"]["model"] == "qwen2.5:7b"


def test_update_instance_404(client):
    r = client.post("/api/instances/nope-1/update", json={"engine": "agy"})
    assert r.status_code == 404
