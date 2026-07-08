from server.agent_library import parse_agent_md


def test_parse_agent_md():
    md = "---\nname: front-end-dev\nrole: Coder\nengine: codex\nskills: [ui-ux-pro-max]\n---\nKinh nghiem React."
    a = parse_agent_md(md)
    assert a.name == "front-end-dev" and a.role == "Coder" and a.engine == "codex"
    assert a.skills == ["ui-ux-pro-max"] and "React" in a.body
