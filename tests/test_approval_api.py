"""API duyệt trên app 7788 (kênh UI, SPEC FR4/FR7). Mock run_approved — không spawn tiến trình thật."""
import importlib
import json
import threading

import pytest
from fastapi.testclient import TestClient

from server import approvals as ap
from server.config import Instance

PIN = "48291637"
INST = [{"name": "lead-1", "engine": "claude", "role": "Lead", "autonomy": "suggest"}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": INST, "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def _req(store, prompt="đọc kỹ việc này"):
    return store.create(Instance(name="g-1", engine="gemini", role="Coder"), prompt, "full")


def test_list_has_full_prompt_for_ui_and_pin_flag(client, _isolated_approvals):
    r = _req(_isolated_approvals)
    d = client.get("/api/approvals").json()
    assert d["pin_set"] is False
    [a] = d["approvals"]
    assert a["id"] == r.id and a["prompt"] == "đọc kỹ việc này" and a["target_level"] == "full"


def test_approve_needs_pin_configured_then_correct_pin_and_runs_once(client, _isolated_approvals, monkeypatch):
    store = _isolated_approvals
    r = _req(store)
    ran, ev = [], threading.Event()
    monkeypatch.setattr(ap, "run_approved", lambda rid, *a, **k: (ran.append(rid), ev.set()))
    res = client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": PIN})
    assert res.status_code == 409 and res.json()["detail"] == "pin_not_set"
    store._pin.set_pin(PIN)
    assert client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": "000000"}).status_code == 403
    assert client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve"}).status_code == 403
    ok = client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": PIN})
    assert ok.status_code == 200 and ok.json()["state"] == "approved"
    assert ev.wait(3) and ran == [r.id]
    assert client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": PIN}).status_code == 409
    assert ran == [r.id]                                      # không chạy lần hai


def test_reject_needs_no_pin_and_does_not_run(client, _isolated_approvals, monkeypatch):
    r = _req(_isolated_approvals)
    monkeypatch.setattr(ap, "run_approved", lambda *a, **k: pytest.fail("không được chạy khi từ chối"))
    res = client.post(f"/api/approvals/{r.id}/decide", json={"decision": "reject"})
    assert res.status_code == 200 and res.json()["state"] == "rejected"


def test_decided_by_comes_from_route_not_body(client, _isolated_approvals):
    r = _req(_isolated_approvals)
    client.post(f"/api/approvals/{r.id}/decide", json={"decision": "reject", "decided_by": "kira"})
    assert _isolated_approvals._reqs[r.id].decided_by == "ui"


def test_unknown_id_404_and_bad_decision_400(client, _isolated_approvals):
    assert client.post("/api/approvals/nope/decide", json={"decision": "reject"}).status_code == 404
    r = _req(_isolated_approvals)
    assert client.post(f"/api/approvals/{r.id}/decide", json={"decision": "maybe"}).status_code == 400


def test_pin_lockout_returns_429(client, _isolated_approvals):
    store = _isolated_approvals
    store._pin.set_pin(PIN)
    r = _req(store)
    codes = [client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": "000000"}).status_code
             for _ in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429


def test_pending_counts_into_attention_without_leaking_prompt(client, _isolated_approvals):
    _req(_isolated_approvals, "RẤT BÍ MẬT")
    d = client.get("/api/jobs").json()
    assert d["summary"]["approvals"] == 1 and d["summary"]["attention"] >= 1
    assert "RẤT BÍ MẬT" not in json.dumps(d, ensure_ascii=False)


def test_no_api_can_set_the_pin(client):
    for method in (client.post, client.put, client.patch):
        assert method("/api/approvals/pin", json={"pin": "123456"}).status_code in (404, 405, 422)
    assert client.post("/api/approvals/pin/set", json={"pin": "123456"}).status_code in (404, 405)


def test_foreign_host_is_refused(client, _isolated_approvals):
    r = client.get("/api/approvals", headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_kira_routes_list_without_prompt_and_only_reject_defer(client, _isolated_approvals):
    store = _isolated_approvals
    r = _req(store, "BÍ MẬT KHÔNG ĐƯỢC LỘ")
    d = client.get("/api/approvals/kira").json()
    assert d["approvals"][0]["id"] == r.id and "BÍ MẬT" not in json.dumps(d, ensure_ascii=False)
    assert client.post(f"/api/approvals/{r.id}/kira/approve").status_code in (404, 405, 422)
    assert store._reqs[r.id].state == "pending"
    assert client.post(f"/api/approvals/{r.id}/kira/defer").json()["state"] == "deferred"
    assert store._reqs[r.id].decided_by == "kira"
    assert client.post(f"/api/approvals/{r.id}/kira/reject").json()["state"] == "rejected"
    assert client.post(f"/api/approvals/{r.id}/kira/reject").status_code == 409
