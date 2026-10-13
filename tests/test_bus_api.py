# -*- coding: utf-8 -*-
import json

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
    from server.bus import BUS
    BUS.clear()
    return TestClient(app_module.app)


def test_bus_post_and_get(client):
    r = client.post("/api/bus", json={"sender": "lead-1", "recipient": "coder-1", "text": "làm X"})
    assert r.status_code == 200
    assert r.json()["message"]["text"] == "làm X"
    g = client.get("/api/bus")
    assert g.status_code == 200
    msgs = g.json()["messages"]
    assert len(msgs) == 1 and msgs[0]["recipient"] == "coder-1"


def test_bus_post_empty_400(client):
    r = client.post("/api/bus", json={"text": "   "})
    assert r.status_code == 400
