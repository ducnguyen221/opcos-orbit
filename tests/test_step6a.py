"""Bước 6a: cwd riêng theo instance (RF8), CLI không chạy từ cwd (RF8), RF6, RF7, RF11, RF12. Mock hết."""
import importlib
import io
import json
import os
import shutil
import sys

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from server import adapters, jobs, paths
from server.config import Instance, load_config


class _Stdin:
    def write(self, t):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    pid = 717171
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO("ok\n")
        self.stdin = _Stdin()

    def wait(self, timeout=None):
        return 0


@pytest.fixture(autouse=True)
def _clean():
    jobs.JOBS.clear()
    yield
    jobs.JOBS.clear()


# --- RF8: cwd riêng ----------------------------------------------------------------------------
def test_instance_has_optional_cwd_and_config_accepts_it(tmp_path):
    assert Instance(name="a", engine="claude").cwd == ""
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"instances": [{"name": "a", "engine": "claude", "cwd": "x"}]}), encoding="utf-8")
    assert load_config(str(f)).instances[0].cwd == "x"


def test_instance_cwd_is_under_workspace_root_and_created(tmp_path):
    root = tmp_path / "ws"
    p = paths.instance_cwd(Instance(name="coder-1", engine="codex"))
    assert os.path.isdir(p) and os.path.realpath(p).startswith(os.path.realpath(os.environ["ORBIT_WORKSPACE_ROOT"]))
    assert os.path.basename(p) == "coder-1"


@pytest.mark.parametrize("evil", ["..\\..\\x", "../../x", "a/b", "C:\\Windows", ".secret", "..", "", "a\x00b"])
def test_instance_cwd_sanitizes_names(evil):
    root = os.path.realpath(os.environ["ORBIT_WORKSPACE_ROOT"])
    p = os.path.realpath(paths.instance_cwd(Instance(name=evil, engine="codex")))
    assert os.path.commonpath([p, root]) == root and p != root


def test_custom_cwd_outside_root_is_ignored(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    p = paths.instance_cwd(Instance(name="x-1", engine="codex", cwd=str(outside)))
    assert os.path.realpath(p) != os.path.realpath(str(outside))


def test_custom_cwd_inside_root_is_used():
    root = os.environ["ORBIT_WORKSPACE_ROOT"]
    inside = os.path.join(root, "projA")
    p = paths.instance_cwd(Instance(name="x-1", engine="codex", cwd=inside))
    assert os.path.realpath(p) == os.path.realpath(inside)


def test_run_agent_spawns_in_instance_cwd_not_repo_root():
    seen = {}

    def fake(argv, **kw):
        seen.update(kw)
        return _Proc()
    inst = Instance(name="c-1", engine="claude", role="R", autonomy="full")
    with patch.object(adapters.subprocess, "Popen", side_effect=fake):
        adapters.run_agent(inst, "việc")
    assert seen["cwd"] == paths.instance_cwd(inst)
    assert os.path.realpath(seen["cwd"]) != os.path.realpath(os.getcwd())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows: which() tìm trong cwd")
def test_cli_lookup_ignores_current_directory(tmp_path, monkeypatch):
    (tmp_path / "evilcli.cmd").write_text("@echo pwned", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert os.environ.get("NoDefaultCurrentDirectoryInExePath") == "1"
    assert shutil.which("evilcli") is None


# --- RF7: prompt bắt đầu bằng "-" ở đường argv (mức full) -----------------------------------------
def test_claude_full_prompt_cannot_become_a_flag():
    inst = Instance(name="c-1", engine="claude", role="R", autonomy="full")
    cmd = adapters.build_command(inst, "--dangerously-skip-permissions", "full")
    i = cmd.index("-p")
    assert not cmd[i + 1].lstrip().startswith("-") and "--dangerously-skip-permissions" in cmd[i + 1]


# --- RF6 / RF12 / RF11 qua API -----------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [
        {"name": "full-1", "engine": "claude", "role": "Lead", "autonomy": "full"},
        {"name": "low-1", "engine": "claude", "role": "Assistant", "autonomy": "suggest"}], "settings": {}}),
        encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    import server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app), app_module, cfg


def test_rf6_cannot_change_engine_or_role_of_full_instance_via_api(client):
    c, _, cfg = client
    for body in ({"engine": "codex"}, {"role": "Coder"}):
        r = c.post("/api/instances/full-1/update", json=body)
        assert r.status_code == 409, body
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["instances"][0]["engine"] == "claude" and data["instances"][0]["role"] == "Lead"


def test_rf6_same_value_or_lower_level_instance_still_editable(client):
    c, _, _ = client
    assert c.post("/api/instances/full-1/update", json={"engine": "claude"}).status_code == 200
    assert c.post("/api/instances/low-1/update", json={"engine": "codex"}).status_code == 200
    assert c.post("/api/instances/full-1/update", json={"autonomy": "suggest"}).status_code == 200   # hạ mức vẫn được


def test_rf12_remote_hint_no_longer_suggests_exposing_port_7788(client):
    _, app_module, _ = client
    hint = app_module.REMOTE_MANUAL_HINT.lower()
    assert "ngrok" not in hint and "tailscale" not in hint.replace("cổng kira", "") or "không" in hint
    assert "7788" in hint and "không" in hint        # nói rõ KHÔNG phơi cổng 7788


@pytest.mark.parametrize("name", ["..\\evil", "../evil", "a/b", "..", "x\x00y", ".hidden", "a" * 100])
def test_rf11_delete_voice_rejects_path_traversal(client, name):
    c, _, _ = client
    with patch("server.voices.os.remove") as rm:
        r = c.delete("/api/voices/" + name.replace("\\", "%5C").replace("/", "%2F").replace("\x00", "%00"))
    assert r.status_code in (400, 404, 405, 422)
    rm.assert_not_called()
