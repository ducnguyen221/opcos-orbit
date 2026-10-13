# Agent Console — Phase 2-4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development. Steps `- [ ]`.

**Goal:** Hoàn thiện Agent Console tới sản phẩm đủ tính năng: thư viện agent + instance có tên (P2), nạp context/folder/upload + PageIndex routing (P3), session rename/resume + Claude resume + remote toggle + autonomy gate (P4).

**Architecture:** Nối tiếp Phase 1 (branch `phase1-build`). Thêm module `server/agent_library.py`, `server/context_manager.py`, `server/session.py`; mở rộng `server/config.py` (autonomy, session_id), `server/adapters.py` (resume, autonomy), `server/app.py` (endpoints REST), `web/` (panel).

**Tech Stack:** như Phase 1 (Python/FastAPI/pytest). Tái dùng `pageindex-mcp` (`~/.mcp/pageindex-mcp/store`).

## Global Constraints
- Repo `~/.mcp/agent-console`, branch `phase1-build`. venv `.venv/Scripts/python.exe`.
- Interface Phase 1 ĐÃ CÓ (dùng lại, không sửa chữ ký): `Instance{name,engine,voice,role,agent_md}`, `Config{instances,settings}`, `load_config(path)`, `Blackboard(session_path).add/turns/transcript_text`, `build_command(inst,prompt)`, `run_agent(inst,prompt,timeout)`, `parse_markers(text)->{delegate,say,ask}`, `run_turn(cfg,bb,user_text,agent_runner)`.
- `.ps1` tiếng Việt = UTF-8 BOM. Không nạp PROTECTED (`.env*`,key,token,`.claude.json`). Không commit `config.json` thật.
- TDD: mỗi task test→fail→implement→pass→commit.

---

### Task 1: Agent Library — parse & discover agent .md
**Files:** Create `server/agent_library.py`, `tests/test_agent_library.py`
**Interfaces:** Produces `parse_agent_md(text:str)->AgentDef` (dataclass `{name,role,engine,model,skills:list,body:str,path:str|None}`); `discover_agents(dirs:list[str])->list[AgentDef]` (quét `*.md` có frontmatter `name`); `scan_folder_for_agents(path:str)->list[AgentDef]`.

- [ ] **Step 1: test** `tests/test_agent_library.py`
```python
from server.agent_library import parse_agent_md
def test_parse_agent_md():
    md = "---\nname: front-end-dev\nrole: Coder\nengine: codex\nskills: [ui-ux-pro-max]\n---\nKinh nghiem React."
    a = parse_agent_md(md)
    assert a.name == "front-end-dev" and a.role == "Coder" and a.engine == "codex"
    assert a.skills == ["ui-ux-pro-max"] and "React" in a.body
```
- [ ] **Step 2: run→fail** `.venv/Scripts/python.exe -m pytest tests/test_agent_library.py -v`
- [ ] **Step 3: implement** `server/agent_library.py`
```python
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
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git add -A && git commit -m "feat(agent_library): parse + discover agent .md"`

---

### Task 2: Instance manager (tạo/đặt tên/sửa/xoá, persist)
**Files:** Create `server/instances.py`, `tests/test_instances.py`
**Interfaces:** Produces `InstanceStore(config_path)` với `.list()->list[Instance]`, `.create(agent:AgentDef, engine:str|None, voice:str)->Instance` (tên `<slug>-<n>`, n tăng dần), `.rename(old,new)`, `.remove(name)`; ghi vào `config.json` key `instances`.

- [ ] **Step 1: test**
```python
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
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** `server/instances.py`
```python
import json, re
from server.config import Instance
from server.agent_library import AgentDef

def _slug(s): return re.sub(r"[^a-z0-9\-]+","-", s.lower()).strip("-") or "agent"

class InstanceStore:
    def __init__(self, config_path: str):
        self.path = config_path
        self.raw = json.load(open(config_path, encoding="utf-8"))
        self.raw.setdefault("instances", []); self.raw.setdefault("settings", {})
    def list(self):
        return [Instance(**{k:v for k,v in i.items() if k in Instance.__dataclass_fields__}) for i in self.raw["instances"]]
    def _save(self):
        json.dump(self.raw, open(self.path,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    def create(self, agent: AgentDef, engine=None, voice="my-voice") -> Instance:
        base = _slug(agent.name)
        n = 1 + sum(1 for i in self.raw["instances"] if i["name"].rsplit("-",1)[0]==base)
        inst = Instance(name=f"{base}-{n}", engine=engine or agent.engine,
                        voice=voice, role=agent.role, agent_md=agent.path)
        self.raw["instances"].append(inst.__dict__); self._save(); return inst
    def rename(self, old, new):
        for i in self.raw["instances"]:
            if i["name"]==old: i["name"]=new
        self._save()
    def remove(self, name):
        self.raw["instances"]=[i for i in self.raw["instances"] if i["name"]!=name]; self._save()
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git commit -am "feat(instances): create/rename/remove persisted to config"`

---

### Task 3: Agent Library API + frontend panel
**Files:** Modify `server/app.py`; Create `web/library.js`; Modify `web/index.html`
**Interfaces:** REST: `GET /api/agents` (discover_agents ở opcos/.claude/kpim), `POST /api/agents/scan {path}`, `GET /api/instances`, `POST /api/instances {agent_name,engine,voice}`, `PATCH /api/instances/{name} {new_name}`, `DELETE /api/instances/{name}`.
- [ ] **Step 1: implement endpoints** (dùng `discover_agents(["~/.opcos/plugins","~/.claude/agents"])` + `InstanceStore`). Thêm vào `server/app.py`.
- [ ] **Step 2: smoke test API** bằng `TestClient` (fastapi.testclient) — `tests/test_library_api.py`: GET /api/agents trả list; POST tạo instance; PATCH rename; assert 200 + JSON.
- [ ] **Step 3: frontend** `web/library.js` + panel trong `index.html`: list agents, nút "Tạo CLI", ô rename, list instances. (~60 dòng JS fetch.)
- [ ] **Step 4: run pytest + commit** `git commit -am "feat(app): agent library API + panel"`

---

### Task 4: Context manager — scan/upload/path + PROTECTED guard
**Files:** Create `server/context_manager.py`, `tests/test_context.py`
**Interfaces:** Produces `is_protected(path)->bool`; `scan_folder(path, max_files=200)->list[dict{path,size,type}]` (bỏ `node_modules/.git`, PROTECTED, cap); `read_text_file(path, max_bytes=100_000)->str`; `save_upload(name, data:bytes, workspace)->str`.
- [ ] **Step 1: test**
```python
from server.context_manager import is_protected, scan_folder
def test_protected():
    assert is_protected("C:/x/.env") and is_protected("a/.claude.json")
    assert not is_protected("src/main.py")
def test_scan_folder_filters(tmp_path):
    (tmp_path/"a.py").write_text("x"); (tmp_path/".env").write_text("SECRET")
    (tmp_path/"node_modules").mkdir(); (tmp_path/"node_modules"/"b.js").write_text("y")
    files = scan_folder(str(tmp_path))
    names = [f["path"].split("/")[-1].split("\\")[-1] for f in files]
    assert "a.py" in names and ".env" not in names and "b.js" not in names
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** `server/context_manager.py`
```python
import os, fnmatch
_PROT = ["*.env", ".env*", "*.pem", "*.key", "*.boto", ".gitconfig", ".claude.json*", "NTUSER.DAT*"]
_SECRET_HINT = ["secret","token","password","api_key","credential"]
_SKIP_DIR = {"node_modules",".git","__pycache__",".venv"}

def is_protected(path: str) -> bool:
    base = os.path.basename(path).lower()
    if any(fnmatch.fnmatch(base, p.lower()) for p in _PROT): return True
    if base in (".env",) or base.startswith(".env"): return True
    return False

def scan_folder(path: str, max_files: int = 200) -> list:
    out = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIR]
        for f in files:
            fp = os.path.join(root, f)
            if is_protected(fp): continue
            try: size = os.path.getsize(fp)
            except OSError: continue
            out.append({"path": fp, "size": size, "type": os.path.splitext(f)[1].lstrip(".")})
            if len(out) >= max_files: return out
    return out

def read_text_file(path: str, max_bytes: int = 100_000) -> str:
    if is_protected(path): return "[PROTECTED — không nạp]"
    with open(path, "rb") as fh: data = fh.read(max_bytes)
    return data.decode("utf-8", errors="replace")

def save_upload(name: str, data: bytes, workspace: str) -> str:
    os.makedirs(workspace, exist_ok=True)
    safe = os.path.basename(name)
    dest = os.path.join(workspace, safe)
    with open(dest, "wb") as fh: fh.write(data)
    return dest
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git commit -am "feat(context): scan/read/upload + PROTECTED guard"`

---

### Task 5: Context routing (dài → PageIndex; ngắn → inline)
**Files:** Modify `server/context_manager.py`; `tests/test_context.py`
**Interfaces:** Produces `route_context(path)->dict{mode:'inline'|'rag'|'skip', content?:str, hint?:str}`. PDF hoặc file > 50KB → `mode='rag'` + hint dùng pageindex (`pi_build_index`); text ngắn → `mode='inline'` + content; PROTECTED/binary → `skip`.
- [ ] **Step 1: test**
```python
from server.context_manager import route_context
def test_route_short_inline(tmp_path):
    p = tmp_path/"n.md"; p.write_text("ngắn")
    r = route_context(str(p)); assert r["mode"]=="inline" and "ngắn" in r["content"]
def test_route_pdf_rag(tmp_path):
    p = tmp_path/"doc.pdf"; p.write_bytes(b"%PDF-1.4 ...")
    assert route_context(str(p))["mode"]=="rag"
def test_route_protected_skip(tmp_path):
    p = tmp_path/".env"; p.write_text("S=1")
    assert route_context(str(p))["mode"]=="skip"
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** (thêm vào context_manager.py)
```python
def route_context(path: str) -> dict:
    if is_protected(path): return {"mode": "skip", "hint": "PROTECTED"}
    ext = os.path.splitext(path)[1].lower()
    try: size = os.path.getsize(path)
    except OSError: return {"mode": "skip", "hint": "không đọc được"}
    if ext == ".pdf" or size > 50_000:
        return {"mode": "rag", "hint": f"Dùng PageIndex: pi_build_index('{path}') rồi pi_get_structure/pi_get_pages để hỏi-đáp trích trang."}
    if ext in (".png",".jpg",".jpeg",".zip",".exe",".mp4",".mp3",".wav"):
        return {"mode": "skip", "hint": "binary"}
    return {"mode": "inline", "content": read_text_file(path)}
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git commit -am "feat(context): route_context (rag/inline/skip)"`

---

### Task 6: Context API + panel + [ATTACH] wire
**Files:** Modify `server/app.py`, `server/orchestrator.py`; Create `web/context.js`
**Interfaces:** REST `POST /api/context/scan {path}`, `POST /api/context/upload` (multipart), `POST /api/context/attach {instance,path}`. Orchestrator: parse `[ATTACH inst: path]` marker → route_context → prepend content/hint vào prompt của instance đó khi DELEGATE.
- [ ] **Step 1: test** `parse_markers` mở rộng `attach` — `tests/test_orchestrator.py::test_parse_attach`: `[ATTACH coder-1: /x/f.py]` → `m["attach"]==[("coder-1","/x/f.py")]`. (Cập nhật `parse_markers` thêm key `attach`.)
- [ ] **Step 2: implement** parse `[ATTACH ...]` (regex giống DELEGATE nhưng path không quote): `\[ATTACH([^\]]*)\]`, tách `name: path`. Trong `run_turn`, trước khi chạy DELEGATE cho instance, nếu có attach cho nó → `route_context(path)` → chèn content (inline) hoặc hint (rag) vào đầu task.
- [ ] **Step 3: endpoints + `web/context.js`** (nút quét folder → list → tick; upload; hiển thị attached). ~50 dòng.
- [ ] **Step 4: run pytest + commit** `git commit -am "feat(context): API + panel + [ATTACH] orchestrator wire"`

---

### Task 7: Session manager (list/new/rename/resume)
**Files:** Create `server/session.py`, `tests/test_session.py`
**Interfaces:** Produces `SessionManager(sessions_dir)` với `.new(name)->str(id)`, `.list()->list[dict{id,name,ts,turns}]`, `.rename(id,name)`, `.load(id)->Blackboard` (mở `<id>.jsonl`). Index ở `sessions/index.json`.
- [ ] **Step 1: test**
```python
from server.session import SessionManager
def test_session_new_rename_load(tmp_path):
    sm = SessionManager(str(tmp_path))
    sid = sm.new("họp sáng")
    bb = sm.load(sid); bb.add("user","User","hi")
    sm.rename(sid, "họp chiều")
    lst = sm.list()
    assert lst[0]["name"]=="họp chiều" and lst[0]["id"]==sid
    bb2 = sm.load(sid); assert len(bb2.turns())==1
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** `server/session.py`
```python
import os, json, time
from server.blackboard import Blackboard

class SessionManager:
    def __init__(self, sessions_dir: str):
        self.dir = sessions_dir; os.makedirs(sessions_dir, exist_ok=True)
        self.index = os.path.join(sessions_dir, "index.json")
        self.data = json.load(open(self.index, encoding="utf-8")) if os.path.exists(self.index) else {}
    def _save(self): json.dump(self.data, open(self.index,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    def new(self, name: str) -> str:
        sid = str(int(time.time()*1000))
        self.data[sid] = {"id": sid, "name": name, "ts": sid}; self._save(); return sid
    def list(self):
        out = []
        for sid, meta in self.data.items():
            p = os.path.join(self.dir, f"{sid}.jsonl")
            n = sum(1 for _ in open(p, encoding="utf-8")) if os.path.exists(p) else 0
            out.append({**meta, "turns": n})
        return sorted(out, key=lambda x: x["ts"], reverse=True)
    def rename(self, sid, name):
        if sid in self.data: self.data[sid]["name"]=name; self._save()
    def load(self, sid) -> Blackboard:
        return Blackboard(os.path.join(self.dir, f"{sid}.jsonl"))
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git commit -am "feat(session): new/list/rename/resume"`

---

### Task 8: Claude session-resume + autonomy gate trong adapter
**Files:** Modify `server/config.py` (thêm `session_id:str=""`, `autonomy:str="suggest"` vào Instance), `server/adapters.py`; `tests/test_adapters.py`
**Interfaces:** `build_command` thêm `--resume <session_id>` khi Instance.claude có session_id. Produces `check_autonomy(inst, action:str)->bool` (suggest: chỉ đọc/hỏi; auto-safe: cho ghi nháp; full: tất cả). Adapter không thay đổi chữ ký `run_agent`.
- [ ] **Step 1: test**
```python
from server.config import Instance
from server.adapters import build_command, check_autonomy
def test_claude_resume_flag():
    inst = Instance(name="lead-1", engine="claude", role="Lead"); inst.session_id="abc123"
    cmd = build_command(inst, "hi")
    assert "--resume" in cmd and "abc123" in cmd
def test_autonomy_levels():
    s = Instance("a","claude"); s.autonomy="suggest"
    f = Instance("b","claude"); f.autonomy="full"
    assert check_autonomy(s,"read") and not check_autonomy(s,"write")
    assert check_autonomy(f,"write")
```
- [ ] **Step 2: run→fail** (Instance chưa có session_id/autonomy).
- [ ] **Step 3: implement** — thêm field vào `Instance` dataclass (`session_id:str=""`, `autonomy:str="suggest"`); trong `build_command` claude: nếu `getattr(inst,'session_id','')` → chèn `--resume <id>` sau `-p`; thêm `check_autonomy`:
```python
def check_autonomy(inst, action: str) -> bool:
    level = getattr(inst, "autonomy", "suggest")
    if level == "full": return True
    if level == "auto-safe": return action in ("read","draft","query")
    return action in ("read","query")
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: commit** `git commit -am "feat(adapters): claude --resume + autonomy gate"`

---

### Task 9: Session + Remote API + panel; final wiring & report
**Files:** Modify `server/app.py`, `web/index.html`, `web/session.js`, `run.ps1`; Create `docs/REPORT-2026-07-03.md` (cập nhật)
**Interfaces:** REST `GET /api/sessions`, `POST /api/sessions {name}`, `PATCH /api/sessions/{id} {name}`, `POST /api/sessions/{id}/resume`, `POST /api/remote/toggle {on:bool}` (chạy `claude` remote-control command; nếu không được → trả hướng dẫn thủ công).
- [ ] **Step 1:** endpoints session (dùng SessionManager) + panel `web/session.js` (list/new/rename/resume). Smoke `TestClient` test GET/POST/PATCH sessions.
- [ ] **Step 2:** nút Remote-control: endpoint chạy `subprocess.run(["claude","remote-control"...])` nếu có; luôn trả trạng thái + hướng dẫn. (Không test live — smoke.)
- [ ] **Step 3:** cập nhật `docs/REPORT-2026-07-03.md`: thêm mục Phase 2-4 (bảng task + pytest), checklist việc cần user (gemini auth, verify OmniVoice GPU, test voice mic, thử remote từ điện thoại).
- [ ] **Step 4:** full pytest + commit `git commit -am "feat(app): session+remote API + panel + report Phase 2-4"`

---

## Self-Review
- **Spec coverage:** agent_library(P2)=T1-3 · context_manager+RAG(P3)=T4-6 · session/resume/remote/autonomy(P4)=T7-9 ✅. `[APPOINT]` marker: orchestrator P1 chưa parse — thêm ở T6 cùng ATTACH (ghi rõ nếu implement được; nếu không, để Minor cho final review).
- **Placeholder scan:** UI tasks (T3/T6/T9) mô tả JS panel thay vì full code — chấp nhận mức plan; endpoints + logic có test thật.
- **Type consistency:** `AgentDef{name,role,engine,model,skills,body,path}`, `InstanceStore.create/list/rename/remove`, `route_context->{mode,content?,hint?}`, `SessionManager.new/list/rename/load`, `check_autonomy(inst,action)` — nhất quán, khớp Instance mở rộng (session_id, autonomy) ở T8.
