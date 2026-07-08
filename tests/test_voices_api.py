import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    import importlib
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_get_voices_returns_list(client, monkeypatch):
    import server.app as app_module
    monkeypatch.setattr(app_module.voices, "list_voices", lambda: ["my-voice", "giong-b"])
    r = client.get("/api/voices")
    assert r.status_code == 200
    assert r.json() == ["my-voice", "giong-b"]


def test_set_default_voice(client, monkeypatch):
    import server.app as app_module
    called = {}
    monkeypatch.setattr(app_module.voices, "set_default", lambda name: called.setdefault("name", name) or "ok")
    r = client.post("/api/voices/default", json={"name": "my-voice"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert called["name"] == "my-voice"


def test_clone_voice_multipart(client, monkeypatch):
    import server.app as app_module
    called = {}

    def fake_clone(wav_path, ref_text, name):
        called["wav_exists"] = os.path.exists(wav_path)
        called["ref_text"] = ref_text
        called["name"] = name
        return "ok"

    monkeypatch.setattr(app_module.voices, "clone_from_wav", fake_clone)
    r = client.post(
        "/api/voices/clone",
        files={"file": ("a.wav", b"RIFFxxxxWAVEfmt ", "audio/wav")},
        data={"ref_text": "xin chào", "name": "test"},
    )
    assert r.status_code == 200
    assert called["ref_text"] == "xin chào"
    assert called["name"] == "test"
    assert called["wav_exists"] is True


def test_create_voice_from_instruct(client, monkeypatch):
    import server.app as app_module
    called = {}
    monkeypatch.setattr(
        app_module.voices, "create_from_instruct",
        lambda instruct, name: called.setdefault("args", (instruct, name)) or "ok",
    )
    r = client.post("/api/voices/create", json={"instruct": "giọng nữ trẻ trung", "name": "giong-c"})
    assert r.status_code == 200
    assert called["args"] == ("giọng nữ trẻ trung", "giong-c")


def test_delete_voice(client, monkeypatch):
    import server.app as app_module
    monkeypatch.setattr(app_module.voices, "delete_voice", lambda name: "deleted")
    r = client.delete("/api/voices/giong-c")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_set_instance_voice_updates_store(client):
    r0 = client.post("/api/instances", json={"agent_name": "front-end-dev", "engine": "codex", "voice": "voice-b"})
    assert r0.status_code == 200
    name = r0.json()["name"]

    r = client.post(f"/api/instances/{name}/voice", json={"voice": "my-voice"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/instances")
    inst = next(i for i in r2.json() if i["name"] == name)
    assert inst["voice"] == "my-voice"


def test_set_instance_voice_unknown_404(client):
    r = client.post("/api/instances/nope/voice", json={"voice": "my-voice"})
    assert r.status_code == 404
