import os, glob
from dataclasses import dataclass, field

@dataclass
class AgentDef:
    name: str
    role: str = "Assistant"
    engine: str = "claude"
    model: str = ""
    skills: list = field(default_factory=list)
    body: str = ""
    path: str | None = None

def _parse_frontmatter(text: str):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_raw, body = text[3:end].strip(), text[end+4:].lstrip("\n")
    fm = {}
    for line in fm_raw.splitlines():
        if ":" not in line: continue
        k, v = line.split(":", 1); k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        fm[k] = v
    return fm, body

def parse_agent_md(text: str, path: str | None = None) -> AgentDef:
    fm, body = _parse_frontmatter(text)
    return AgentDef(name=fm.get("name","agent"), role=fm.get("role","Assistant"),
                    engine=fm.get("engine","claude"), model=fm.get("model",""),
                    skills=fm.get("skills",[]) if isinstance(fm.get("skills",[]),list) else [],
                    body=body, path=path)

def discover_agents(dirs: list[str]) -> list[AgentDef]:
    out = []
    for d in dirs:
        for f in glob.glob(os.path.join(os.path.expanduser(d), "**", "*.md"), recursive=True):
            try:
                t = open(f, encoding="utf-8").read()
                if t.lstrip().startswith("---") and "name:" in t[:200]:
                    out.append(parse_agent_md(t, f))
            except Exception: continue
    return out

def scan_folder_for_agents(path: str) -> list[AgentDef]:
    return discover_agents([path])
