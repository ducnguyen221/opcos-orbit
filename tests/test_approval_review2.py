"""Vòng sửa sau security review lần 2 của giao thức duyệt (RF1–RF8). Mock hết — không spawn, không ~/.secret."""
import importlib
import io
import json
import pathlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import adapters, approvals as ap, jobs
from server.config import Instance

PIN = "48291637"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def inst(name="g-1", engine="gemini", **kw):
    return Instance(name=name, engine=engine, role="Coder", **kw)


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    pin = ap.PinStore(str(tmp_path / "pin.json"), now=clock)
    pin.set_pin(PIN)
    store = ap.ApprovalStore(now=clock, log_path=str(tmp_path / "approvals.jsonl"), pin=pin)
    return store, clock, pin, tmp_path


# RF1 ---------------------------------------------------------------------------------------------
def test_ui_view_exposes_limits_and_bypass_flag(env):
    store, _, _, _ = env
    i = inst(engine="agy", skip_permissions=True)
    i.limit_reason = "bị giới hạn bởi tin từ x (nguồn không xác thực)"
    i.limit_untrusted = True
    v = store.ui_view(store.create(i, "p", "full").id)
    assert v["limit_untrusted"] is True and "không xác thực" in v["limit_reason"]
    assert v["skip_permissions"] is True and v["runs_with_bypass"] is True
    safe = store.create(inst(name="g-2"), "p", "full")
    assert store.ui_view(safe.id)["runs_with_bypass"] is False


def test_untrusted_source_needs_explicit_confirmation(env):
    store, _, _, _ = env
    i = inst()
    i.limit_untrusted = True
    r = store.create(i, "p", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "approve", "ui", pin=PIN)
    assert e.value.code == "confirm_untrusted"
    assert store.decide(r.id, "approve", "ui", pin=PIN, confirm_untrusted=True).state == "approved"


# RF2 ---------------------------------------------------------------------------------------------
def test_pin_lock_backs_off_progressively(env):
    _, clock, pin, _ = env
    for _ in range(5):
        pin.verify("00000000")
    clock.t += ap.PIN_LOCK_S + 1                         # hết khoá lần 1
    for _ in range(5):
        pin.verify("00000000")
    clock.t += ap.PIN_LOCK_S + 1                         # khoá lần 2 dài gấp đôi: vẫn còn khoá
    assert pin.verify(PIN) is False
    clock.t += ap.PIN_LOCK_S + 1
    assert pin.verify(PIN) is True


# RF3 ---------------------------------------------------------------------------------------------
def test_pin_hash_is_cached_once_loaded(env):
    _, _, pin, tmp = env
    assert pin.verify(PIN) is True
    other = ap.PinStore(str(tmp / "other.json"), now=Clock())
    other.set_pin("99999999")
    (tmp / "pin.json").write_text((tmp / "other.json").read_text())     # kẻ ghi đè tệp băm sau khi đã nạp
    assert pin.verify(PIN) is True and pin.verify("99999999") is False


def test_pin_min_length_is_eight(tmp_path):
    p = ap.PinStore(str(tmp_path / "p.json"), now=Clock())
    with pytest.raises(ValueError):
        p.set_pin("1234567")
    p.set_pin("12345678")


# RF4 ---------------------------------------------------------------------------------------------
def test_approved_request_survives_short_grace_after_ttl(env):
    store, clock, _, _ = env
    r = store.create(inst(), "p", "full")
    clock.t += ap.TTL_S - 1
    store.decide(r.id, "approve", "ui", pin=PIN)
    clock.t += 10                                        # quá hạn gốc, còn trong thời gian ân hạn
    assert store.take_for_run(r.id).state == "consumed"


# RF6 ---------------------------------------------------------------------------------------------
def test_prompt_cap_and_terminal_states_drop_full_prompt(env):
    store, _, _, _ = env
    with pytest.raises(ap.ApprovalError) as e:
        store.create(inst(), "x" * (ap.MAX_PROMPT + 1), "full")
    assert e.value.code == "prompt_too_long"
    r = store.create(inst(), "y" * 5000, "full")
    store.decide(r.id, "reject", "ui")
    assert len(r.prompt_final) <= ap.TERMINAL_PROMPT_KEEP


def test_log_rotates_when_large(env, monkeypatch):
    store, _, _, tmp = env
    monkeypatch.setattr(ap, "LOG_MAX_BYTES", 300)
    for n in range(6):
        r = store.create(inst(name=f"i{n}"), "p", "full")
        store.decide(r.id, "reject", "ui")
    assert (tmp / "approvals.jsonl.1").exists()
    assert (tmp / "approvals.jsonl").stat().st_size < 2000


# RF7 ---------------------------------------------------------------------------------------------
def test_timeout_is_part_of_snapshot_and_hash(env):
    store, _, _, _ = env
    a = store.create(inst(), "p", "full", timeout=45)
    b = store.create(inst(), "p", "full", timeout=90)
    assert a.instance["timeout"] == 45 and a.job_fp != b.job_fp


# RF8 ---------------------------------------------------------------------------------------------
def test_override_level_is_only_used_by_adapters_and_approvals():
    root = pathlib.Path(__file__).resolve().parent.parent / "server"
    users = {p.name for p in root.glob("*.py") if "override_level=" in p.read_text(encoding="utf-8")}
    assert users <= {"adapters.py", "approvals.py"}, users


# RF5 + RF7 qua run_approved ------------------------------------------------------------------------
class _Stdin:
    def write(self, t):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    pid = 616161
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO("xong\n")
        self.stdin = _Stdin()

    def wait(self, timeout=None):
        return 0


def _approved(store, **run_kw):
    store._pin.set_pin(PIN)
    with patch.object(adapters.subprocess, "Popen", side_effect=lambda *a, **k: _Proc()):
        adapters.run_agent(inst(), "việc đã đọc kỹ", **run_kw)
    [req] = store.list_pending()
    store.decide(req.id, "approve", "ui", pin=PIN)
    return req


def test_run_approved_failure_is_recorded_not_swallowed(_isolated_approvals):
    store = _isolated_approvals
    jobs.JOBS.clear()
    req = _approved(store)

    def boom(i, p, timeout=None, override_level=None):
        raise RuntimeError("hỏng giữa chừng")
    out = ap.run_approved(req.id, runner=boom)
    assert out.startswith("[ERROR]") and "hỏng giữa chừng" in out
    assert "hỏng giữa chừng" in store.ui_view(req.id)["result"]
    ev = [json.loads(x)["event"] for x in open(store._log_path, encoding="utf-8")]
    assert ev[-2:] == ["consumed", "failed"]


def test_run_approved_passes_original_timeout(_isolated_approvals):
    store = _isolated_approvals
    req = _approved(store, timeout=45)
    assert req.instance["timeout"] == 45
    seen = {}
    ap.run_approved(req.id, runner=lambda i, p, timeout=None, override_level=None: seen.update(t=timeout) or "ok")
    assert seen["t"] == 45


# RF1 qua API ---------------------------------------------------------------------------------------
def test_api_untrusted_requires_confirm_flag_and_exposes_limits(tmp_path, monkeypatch, _isolated_approvals):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [{"name": "lead-1", "engine": "claude", "role": "Lead",
                                               "autonomy": "suggest"}], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    import server.app as app_module
    importlib.reload(app_module)
    client = TestClient(app_module.app)
    store = _isolated_approvals
    store._pin.set_pin(PIN)
    i = Instance(name="g-1", engine="agy", role="Coder", skip_permissions=True)
    i.limit_untrusted, i.limit_reason = True, "nguồn không xác thực"
    r = store.create(i, "p", "full")
    a = client.get("/api/approvals").json()["approvals"][0]
    assert a["limit_untrusted"] is True and a["runs_with_bypass"] is True
    res = client.post(f"/api/approvals/{r.id}/decide", json={"decision": "approve", "pin": PIN})
    assert res.status_code == 409 and res.json()["detail"] == "confirm_untrusted"
    ok = client.post(f"/api/approvals/{r.id}/decide",
                     json={"decision": "approve", "pin": PIN, "confirm_untrusted": True})
    assert ok.status_code == 200
