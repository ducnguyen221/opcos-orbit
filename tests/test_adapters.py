from server.config import Instance
from server.adapters import build_command, check_autonomy

def test_build_command_claude_includes_prompt_and_role():
    inst = Instance(name="lead-1", engine="claude", role="Lead")
    cmd = build_command(inst, "làm X")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert any("Lead" in c for c in cmd)   # role vào system prompt

def test_build_command_codex_and_gemini():
    assert build_command(Instance("c","codex",role="Coder"), "hi")[0] == "codex"
    assert build_command(Instance("g","gemini",role="Researcher"), "hi")[0] == "gemini"

def test_claude_resume_flag():
    inst = Instance(name="lead-1", engine="claude", role="Lead")
    inst.session_id = "abc123"
    cmd = build_command(inst, "hi")
    assert "--resume" in cmd and "abc123" in cmd

def test_autonomy_levels():
    s = Instance("a", "claude"); s.autonomy = "suggest"
    f = Instance("b", "claude"); f.autonomy = "full"
    assert check_autonomy(s, "read") and not check_autonomy(s, "write")
    assert check_autonomy(f, "write")


def test_build_command_agy():
    from server.config import Instance
    from server.adapters import build_command
    inst = Instance(name="researcher-1", engine="agy", role="Researcher")
    cmd = build_command(inst, "tìm X")
    assert cmd[0] == "agy" and "-p" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert any("Researcher" in c for c in cmd)
    # session
    inst.session_id = "conv123"
    assert "--conversation" in build_command(inst, "y") and "conv123" in build_command(inst, "y")


def test_resolve_windows_shims():
    from unittest.mock import patch
    from server.adapters import _resolve
    with patch("server.adapters.shutil.which", return_value=r"C:\x\claude.CMD"):
        assert _resolve("claude")[:2] == ["cmd", "/c"]
    with patch("server.adapters.shutil.which", return_value=r"C:\x\x.ps1"):
        assert _resolve("x")[0] == "powershell"
    with patch("server.adapters.shutil.which", return_value=r"C:\x\agy.exe"):
        assert _resolve("agy") == [r"C:\x\agy.exe"]
    with patch("server.adapters.shutil.which", return_value=None):
        assert _resolve("nope") == ["nope"]


def test_run_ollama_success_uses_stdlib_urllib():
    """Engine ollama: parse content, job done(0), gọi đúng URL+model. Mock urllib
    (stdlib) — regression: KHÔNG được phụ thuộc `requests` (thiếu module = crash cả turn)."""
    import io, json
    from unittest.mock import patch, MagicMock
    from server import adapters, jobs
    from server.config import Instance

    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"message": {"content": "Hello, world."}}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    inst = Instance(name="draft-x", engine="ollama", role="Trợ lý")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = adapters.run_agent(inst, "dịch đi", timeout=30)
    assert out == "Hello, world."
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"]["model"] == "qwen2.5:7b"      # mặc định
    assert captured["body"]["stream"] is False
    j = jobs.list_jobs()[0]
    assert j["engine"] == "ollama" and j["state"] == "done" and j["exit_code"] == 0


def test_run_ollama_error_marks_job_failed():
    """Ollama server down → trả [ERROR], job error(exit 1), KHÔNG ném exception ra ngoài."""
    from unittest.mock import patch
    from server import adapters, jobs
    from server.config import Instance

    inst = Instance(name="draft-y", engine="ollama", role="Trợ lý")
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        out = adapters.run_agent(inst, "dịch đi", timeout=5)
    assert out.startswith("[ERROR]") and "connection refused" in out
    j = jobs.list_jobs()[0]
    assert j["state"] == "error" and j["exit_code"] == 1


def test_stop_all_jobs_kills_registry():
    from unittest.mock import patch
    from server import adapters
    class FakeP:  # đối tượng giả trong registry
        pid = 99999
    adapters.RUNNING[99999] = FakeP()
    with patch("server.adapters._kill_tree") as k:
        n = adapters.stop_all_jobs()
    assert n == 1 and 99999 not in adapters.RUNNING
    k.assert_called_once_with(99999)
