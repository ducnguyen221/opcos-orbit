"""Bảo mật: cổng tự trị phải nằm ở ĐƯỜNG THỰC THI (run_agent), fail-closed;
cờ --dangerously-skip-permissions của agy không được đặt cứng."""
from unittest.mock import patch
from server import adapters
from server.config import Instance


def _agy(**kw):
    inst = Instance(name="r-1", engine="agy", role="Researcher")
    for k, v in kw.items():
        setattr(inst, k, v)
    return inst


def test_agy_default_has_no_skip_permissions_flag():
    assert "--dangerously-skip-permissions" not in adapters.build_command(_agy(), "x")


def test_agy_flag_needs_full_and_explicit_opt_in():
    # full nhưng chưa opt-in -> không cờ
    assert "--dangerously-skip-permissions" not in adapters.build_command(_agy(autonomy="full"), "x")
    # opt-in nhưng chỉ suggest/auto-safe -> không cờ
    for lvl in ("suggest", "auto-safe", "", "bogus"):
        assert "--dangerously-skip-permissions" not in adapters.build_command(
            _agy(autonomy=lvl, skip_permissions=True), "x")
    # đủ cả hai -> có cờ
    assert "--dangerously-skip-permissions" in adapters.build_command(
        _agy(autonomy="full", skip_permissions=True), "x")


def test_run_agent_never_spawns_dangerous_flag_for_suggest():
    inst = _agy(autonomy="suggest", skip_permissions=True)
    argv = []
    def fake_popen(real, **kw):
        argv.extend(real); raise OSError("stop")
    with patch("server.adapters.subprocess.Popen", side_effect=fake_popen):
        adapters.run_agent(inst, "xoá hết", timeout=5)
    assert argv and "--dangerously-skip-permissions" not in argv


def test_run_agent_denies_write_class_when_gate_says_no(monkeypatch):
    monkeypatch.setattr(adapters, "check_autonomy", lambda i, a: a != "write")
    inst = _agy(autonomy="full", skip_permissions=True)
    with patch("server.adapters.subprocess.Popen") as popen:
        out = adapters.run_agent(inst, "x", timeout=5)
    assert out.startswith("[ERROR]") and "autonomy" in out
    popen.assert_not_called()


def test_run_agent_goes_through_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, "check_autonomy", lambda i, a: calls.append(a) or False)
    with patch("server.adapters.subprocess.Popen") as popen:
        out = adapters.run_agent(Instance(name="c", engine="claude"), "hi", timeout=5)
    assert calls and out.startswith("[ERROR]")
    popen.assert_not_called()


def test_gate_fail_closed_on_error(monkeypatch):
    def boom(i, a): raise RuntimeError("cấu hình hỏng")
    monkeypatch.setattr(adapters, "check_autonomy", boom)
    with patch("server.adapters.subprocess.Popen") as popen:
        out = adapters.run_agent(Instance(name="c", engine="claude"), "hi", timeout=5)
    assert out.startswith("[ERROR]")
    popen.assert_not_called()


def test_ollama_also_gated(monkeypatch):
    monkeypatch.setattr(adapters, "check_autonomy", lambda i, a: False)
    with patch("urllib.request.urlopen") as u:
        out = adapters.run_agent(Instance(name="o", engine="ollama"), "hi", timeout=5)
    assert out.startswith("[ERROR]")
    u.assert_not_called()


def test_check_autonomy_fail_closed_inputs():
    class NoField: pass
    assert not adapters.check_autonomy(NoField(), "write")
    i = Instance("a", "claude"); i.autonomy = None
    assert not adapters.check_autonomy(i, "write")
    i.autonomy = "FULL "          # giá trị lạ -> suggest, không phải full
    assert not adapters.check_autonomy(i, "write")
    i.autonomy = "suggest"
    assert not adapters.check_autonomy(i, "unknown-action")
    assert not adapters.check_autonomy(i, None)
