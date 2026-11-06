"""Bảo mật: cổng tự trị phải nằm ở ĐƯỜNG THỰC THI (run_agent), fail-closed;
cờ --dangerously-skip-permissions của agy không được đặt cứng.
P9 TK3a: dưới mức full, không instance nào ghi được (claude/codex chạy chỉ-đọc,
gemini/agy bị từ chối trước Popen)."""
import io
import json
from unittest.mock import patch

import pytest

from server import adapters, jobs
from server.config import Instance

BELOW_FULL = ["suggest", "auto-safe", "", "bogus", None]
FORBIDDEN = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
             "bypassPermissions", "--dangerously-bypass-approvals-and-sandbox",
             "danger-full-access", "workspace-write", "--approve-for-me", "--yolo",
             "yolo", "auto_edit", "--add-dir"}
EVIL = 'p" --sandbox danger-full-access "q'


def _role_sys(role):
    return f"Bạn đóng vai {role} trong một nhóm agent do Lead điều phối. Trả lời ngắn gọn, đúng vai."


class _Stdin:
    def __init__(self):
        self.data, self.closed = "", False

    def write(self, t):
        self.data += t

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _Proc:
    pid = 424242
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO("ok\n")
        self.stdin = _Stdin()

    def wait(self, timeout=None):
        return 0


class _Spawn:
    def __init__(self):
        self.calls, self.kwargs, self.procs = [], [], []


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Gốc rò trạng thái có từ trước: JOBS toàn cục làm
    test_adapters::test_run_ollama_success_uses_stdlib_urllib đỏ khi chạy sau file này."""
    jobs.JOBS.clear()
    yield
    jobs.JOBS.clear()


@pytest.fixture
def spawn(monkeypatch):
    sp = _Spawn()

    def fake_popen(argv, **kw):
        p = _Proc()
        sp.calls.append(list(argv))
        sp.kwargs.append(kw)
        sp.procs.append(p)
        return p

    monkeypatch.setattr(adapters.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(adapters, "_resolve", lambda name: [name])
    return sp


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


def test_run_agent_never_spawns_dangerous_flag_below_full(spawn):
    """T12 — viết lại test cũ `..._for_suggest`. Cũ: agy+suggest TỚI được Popen
    (`assert argv and ...`). Mới (P9 FR2/FR3): agy không có chế độ chỉ-đọc nên bị TỪ CHỐI
    trước Popen; mọi engine còn lại nếu có spawn thì argv không bao giờ chứa cờ bỏ-quyền.
    Giữ hồi quy gốc: cờ bỏ-quyền không bao giờ có dưới full."""
    for engine in ("claude", "codex", "gemini", "agy", "ollama"):
        for lvl in BELOW_FULL:
            inst = Instance(name="r-1", engine=engine, role="Researcher",
                            autonomy=lvl, skip_permissions=True)
            with patch("urllib.request.urlopen", side_effect=OSError("stop")):
                out = adapters.run_agent(inst, "xoá hết", timeout=5)
            if engine in ("agy", "gemini"):
                assert out.startswith("[ERROR]")
    assert not any(a[0] in ("agy", "gemini") for a in spawn.calls)
    for argv in spawn.calls:
        assert not (set(argv) & FORBIDDEN), argv


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


# ---------------------------------------------------------------- P9 TK3a --
CLAUDE_RO = ["claude", "-p", "--restricted", "--permission-mode", "plan",
             "--permission-prompts", "none", "--tools", "Read,Grep,Glob",
             "--strict-mcp-config", "--disable-slash-commands", "--append-system-prompt"]
CODEX_RO = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
            "-c", "approval_policy=never", "--skip-git-repo-check"]   # vòng 3: bỏ "-" trần (PS 5.1 -File coi là tên tham số rỗng); codex exec không có prompt đối số thì đọc stdin


@pytest.mark.parametrize("lvl", BELOW_FULL)
def test_claude_readonly_flags_below_full(spawn, lvl):  # T1
    inst = Instance(name="l", engine="claude", role="Lead", autonomy=lvl)
    adapters.run_agent(inst, "hi", timeout=5)
    assert spawn.calls == [CLAUDE_RO + [_role_sys("Lead")]]


@pytest.mark.parametrize("lvl", BELOW_FULL)
def test_codex_readonly_flags_below_full(spawn, lvl):  # T1
    inst = Instance(name="c", engine="codex", role="Coder", autonomy=lvl)
    adapters.run_agent(inst, "hi", timeout=5)
    assert spawn.calls == [CODEX_RO]


def test_claude_readonly_keeps_resume_after_flags(spawn):  # T1
    inst = Instance(name="l", engine="claude", role="Lead", session_id="abc")
    adapters.run_agent(inst, "hi", timeout=5)
    argv = spawn.calls[0]
    assert argv[-2:] == ["--resume", "abc"] and argv[:len(CLAUDE_RO)] == CLAUDE_RO


@pytest.mark.parametrize("engine", ["gemini", "agy"])
@pytest.mark.parametrize("lvl", ["suggest", "auto-safe", "", "bogus"])
def test_refuse_engine_without_readonly(spawn, engine, lvl):  # T2 + T10 (FR10)
    inst = Instance(name="res-1", engine=engine, role="Researcher", autonomy=lvl)
    out = adapters.run_agent(inst, "hi", timeout=5)
    assert spawn.calls == []
    assert out.startswith("[ERROR]")
    shown = lvl if lvl in ("suggest", "auto-safe") else "suggest"
    for needle in ("res-1", shown, engine, "config.json", "autonomy", "full"):
        assert needle in out, (needle, out)
    j = jobs.list_jobs()[0]
    assert j["state"] == "error" and j["exit_code"] == 1


@pytest.mark.parametrize("engine", ["claude", "codex", "gemini", "agy", "ollama"])
@pytest.mark.parametrize("lvl", BELOW_FULL)
@pytest.mark.parametrize("skip", [True, False])
def test_no_dangerous_flags_below_full(spawn, engine, lvl, skip):  # T3
    inst = Instance(name="x", engine=engine, role="Coder", autonomy=lvl, skip_permissions=skip)
    with patch("urllib.request.urlopen", side_effect=OSError("stop")):
        adapters.run_agent(inst, "hi", timeout=5)
    for argv in spawn.calls:
        assert not (set(argv) & FORBIDDEN)


def test_full_argv_unchanged(spawn):  # T4 (FR4)
    adapters.run_agent(Instance("l", "claude", role="Lead", autonomy="full"), "hi", timeout=5)
    adapters.run_agent(Instance("c", "codex", role="Coder", autonomy="full"), "hi", timeout=5)
    adapters.run_agent(Instance("g", "gemini", role="Researcher", autonomy="full"), "hi", timeout=5)
    adapters.run_agent(Instance("a", "agy", role="Researcher", autonomy="full"), "hi", timeout=5)
    adapters.run_agent(Instance("a", "agy", role="Researcher", autonomy="full",
                                skip_permissions=True), "hi", timeout=5)
    assert spawn.calls == [
        ["claude", "-p", "hi", "--append-system-prompt", _role_sys("Lead")],
        ["codex", "exec", "[Coder] hi"],
        ["gemini", "-p", "[Researcher] hi"],
        ["agy", "-p", "[Researcher] hi"],
        ["agy", "-p", "[Researcher] hi", "--dangerously-skip-permissions"],
    ]
    assert all("stdin" not in kw for kw in spawn.kwargs)


def test_build_command_old_signature_and_level_param():  # T5
    inst = Instance("l", "claude", role="Lead", autonomy="full")
    assert adapters.build_command(inst, "hi")[2] == "hi"
    assert "--restricted" in adapters.build_command(inst, "hi", level="suggest")
    assert "--restricted" not in adapters.build_command(inst, "hi", level="full")


def test_gate_error_or_false_refuses_claude_codex_suggest(spawn, monkeypatch):  # T6
    for engine in ("claude", "codex"):
        inst = Instance(name="c", engine=engine, autonomy="suggest")
        monkeypatch.setattr(adapters, "check_autonomy", lambda i, a: False)
        assert adapters.run_agent(inst, "hi", timeout=5).startswith("[ERROR]")

        def boom(i, a): raise RuntimeError("hỏng")
        monkeypatch.setattr(adapters, "check_autonomy", boom)
        assert adapters.run_agent(inst, "hi", timeout=5).startswith("[ERROR]")
    assert spawn.calls == []


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_prompt_not_in_argv_goes_via_stdin(spawn, engine):  # T7 (RF2, RF7)
    inst = Instance(name="x", engine=engine, role="Coder", autonomy="suggest")
    adapters.run_agent(inst, EVIL, timeout=5)
    argv = spawn.calls[0]
    assert not any("sandbox danger" in a or EVIL in a for a in argv)
    assert spawn.kwargs[0].get("stdin") == adapters.subprocess.PIPE
    assert EVIL in spawn.procs[0].stdin.data and spawn.procs[0].stdin.closed


def test_claude_dash_prompt_not_a_flag(spawn):  # T8
    inst = Instance(name="x", engine="claude", role="Lead", autonomy="suggest")
    adapters.run_agent(inst, "--dangerously-skip-permissions", timeout=5)
    assert "--dangerously-skip-permissions" not in spawn.calls[0]
    assert spawn.procs[0].stdin.data == "--dangerously-skip-permissions"


def test_stdin_broken_pipe_does_not_hang_or_raise(spawn, monkeypatch):
    def bad_write(self, t): raise BrokenPipeError()
    monkeypatch.setattr(_Stdin, "write", bad_write)
    inst = Instance(name="x", engine="codex", role="Coder", autonomy="suggest")
    assert adapters.run_agent(inst, "hi", timeout=5).startswith("ok")


@pytest.mark.parametrize("lvl", BELOW_FULL + ["full"])
def test_ollama_unchanged_all_levels(lvl):  # T9
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"message": {"content": "xin chào"}}).encode()

    bodies = []

    def fake(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return FakeResp()

    inst = Instance(name="o", engine="ollama", role="Drafter", autonomy=lvl)
    with patch("urllib.request.urlopen", side_effect=fake):
        assert adapters.run_agent(inst, "hi", timeout=5) == "xin chào"
    assert bodies[0]["messages"][1]["content"] == "hi"


def test_gate_refusal_message_tells_how_to_raise(spawn, monkeypatch):  # T10 (FR10)
    monkeypatch.setattr(adapters, "check_autonomy", lambda i, a: False)
    out = adapters.run_agent(Instance(name="c-9", engine="claude", autonomy="suggest"), "x", timeout=5)
    for needle in ("c-9", "suggest", "config.json", "full"):
        assert needle in out


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_suggest_via_cmd_shim_prompt_in_stdin_not_argv(monkeypatch, spawn, engine):  # vòng 2
    """Dưới full qua shim cmd /c: prompt đầy ký tự đặc biệt cmd không nằm trong argv, đi stdin."""
    monkeypatch.setattr(adapters, "_resolve", lambda n: ["cmd", "/c", r"C:\x\shim.cmd"])
    nasty = 'x" & calc & "%PATH%^!'
    inst = Instance(name="c", engine=engine, role="Coder", autonomy="suggest")
    out = adapters.run_agent(inst, nasty, timeout=5)
    assert out.startswith("ok") and len(spawn.calls) == 1
    argv = spawn.calls[0]
    assert argv[:3] == ["cmd", "/c", r"C:\x\shim.cmd"]
    assert not any(adapters._CMD_META.search(a) for a in argv[3:])
    assert nasty in spawn.procs[0].stdin.data


@pytest.mark.parametrize("engine", ["claude", "codex", "gemini", "agy"])
@pytest.mark.parametrize("lvl", ["suggest", "auto-safe", "", "bogus", None])
def test_no_bare_dash_in_argv_below_full(spawn, engine, lvl):  # vòng 3
    inst = Instance(name="x", engine=engine, role="Coder", autonomy=lvl)
    adapters.run_agent(inst, "hi", timeout=5)
    for argv in spawn.calls:
        assert "-" not in argv
    if engine == "codex":
        assert spawn.procs[0].stdin.data == "[Coder] hi"


# ---------------------------------------------------------------- vòng 4 --
@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_readonly_run_appends_notice_line(spawn, engine):  # RF2 (a)
    inst = Instance(name="c-1", engine=engine, role="Coder", autonomy="suggest")
    out = adapters.run_agent(inst, "hi", timeout=5)
    last = out.splitlines()[-1]
    assert out.startswith("ok") and last.startswith("[chỉ-đọc]")
    for needle in ("c-1", "suggest", "full", "config.json", "autonomy"):
        assert needle in last


def test_full_run_has_no_readonly_notice(spawn):  # RF2 (a)
    inst = Instance(name="c-1", engine="claude", role="Coder", autonomy="full")
    assert "[chỉ-đọc]" not in adapters.run_agent(inst, "hi", timeout=5)


def test_readonly_notice_names_limiting_source(spawn):  # RF2 (b)
    inst = Instance(name="c-1", engine="codex", role="Coder", autonomy="suggest")
    inst.limit_reason = "bị giới hạn bởi Lead lead-1 ở mức suggest"
    out = adapters.run_agent(inst, "hi", timeout=5)
    assert "bị giới hạn bởi Lead lead-1 ở mức suggest" in out.splitlines()[-1]


def test_refusal_names_limiting_source(spawn):  # RF2 (b)
    inst = Instance(name="g-1", engine="gemini", role="Researcher", autonomy="suggest")
    inst.limit_reason = "bị giới hạn bởi tin từ researcher-1 ở mức suggest"
    out = adapters.run_agent(inst, "hi", timeout=5)
    assert out.startswith("[ERROR]") and "tin từ researcher-1" in out and spawn.calls == []


def test_unknown_engine_below_full_refused_before_popen(spawn):  # allowlist
    inst = Instance(name="n-1", engine="newbot", role="X", autonomy="suggest")
    out = adapters.run_agent(inst, "hi", timeout=5)
    assert out.startswith("[ERROR]") and "config.json" in out and spawn.calls == []
