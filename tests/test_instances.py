import json, tempfile, os
from server.agent_library import AgentDef
from server.instances import InstanceStore
def test_create_and_rename(tmp_path):
    cfg = tmp_path/"config.json"; cfg.write_text(json.dumps({"instances":[],"settings":{}}), encoding="utf-8")
    st = InstanceStore(str(cfg))
    a = AgentDef(name="front-end-dev", role="Coder", engine="codex")
    i1 = st.create(a, None, "voice-b"); i2 = st.create(a, None, "voice-b")
    assert i1.name == "front-end-dev-1" and i2.name == "front-end-dev-2"
    st.rename("front-end-dev-1", "fe-lead")
    assert any(x.name=="fe-lead" for x in st.list())
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert len(saved["instances"]) == 2


def test_create_after_remove_no_collision(tmp_path):
    import json as _json
    from server.agent_library import AgentDef
    from server.instances import InstanceStore
    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    st = InstanceStore(str(cfg))
    a = AgentDef(name="front-end-dev", role="Coder", engine="codex")
    st.create(a, None, "v"); st.create(a, None, "v"); st.create(a, None, "v")  # -1,-2,-3
    st.remove("front-end-dev-2")
    i4 = st.create(a, None, "v")
    names = [x.name for x in st.list()]
    assert i4.name == "front-end-dev-4"          # không tái dùng -2
    assert len(names) == len(set(names))          # không trùng


def test_update_fields(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [
        {"name": "researcher-1", "engine": "gemini", "role": "Researcher"}], "settings": {}}), encoding="utf-8")
    st = InstanceStore(str(cfg))
    out = st.update("researcher-1", engine="agy", model="qwen2.5:7b", role=None)
    assert out is not None
    got = st.list()[0]
    assert got.engine == "agy" and got.model == "qwen2.5:7b"
    assert got.role == "Researcher"              # role=None → giữ nguyên
    assert st.update("khong-ton-tai", engine="agy") is None


def test_update_enforces_single_lead(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [
        {"name": "a-1", "engine": "claude", "role": "Lead"},
        {"name": "b-1", "engine": "codex", "role": "Coder"}], "settings": {}}), encoding="utf-8")
    st = InstanceStore(str(cfg))
    st.update("b-1", role="Lead")                 # đặt b-1 làm Lead
    roles = {i.name: i.role for i in st.list()}
    assert roles["b-1"] == "Lead"
    assert roles["a-1"] == "Assistant"            # Lead cũ bị hạ → DUY NHẤT 1 Lead


def test_update_ignores_unknown_fields(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [
        {"name": "x-1", "engine": "claude", "role": "Coder"}], "settings": {}}), encoding="utf-8")
    st = InstanceStore(str(cfg))
    st.update("x-1", bogus="zzz", role="Reviewer")   # 'bogus' không phải field Instance
    got = st.list()[0]
    assert got.name == "x-1" and got.role == "Reviewer"
    assert not hasattr(got, "bogus")                 # field lạ bị bỏ qua
