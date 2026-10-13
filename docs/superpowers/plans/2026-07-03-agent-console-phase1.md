# Agent Console — Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web local đàm thoại voice điều phối 3 CLI (Claude Lead + Codex + Gemini): nói → STT → Lead phân việc → tổng hợp → đọc trả lời, hiện transcript.

**Architecture:** FastAPI + WebSocket (Python, cùng tiến trình OmniVoice/Whisper). Orchestrator "Lead điều phối" parse marker `[APPOINT]/[DELEGATE]/[SAY]`, chạy adapter (spawn CLI headless), gom vào blackboard, đọc `[SAY]` bằng OmniVoice. Frontend vanilla JS (mic push-to-talk + WS + phát audio).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, websockets, faster-whisper (đã có ở `.tts`), OmniVoice (`.tts/omnivoice`), pytest. CLI: `claude`/`codex`/`gemini`.

## Global Constraints
- Vị trí: `~/.mcp/agent-console`. venv riêng `.venv`. `install.ps1` UTF-8 **BOM** (ACP=1252).
- Kế thừa core.md: không nạp PROTECTED (`.env*`, key, `.claude.json`); localhost mặc định.
- 3 mức tự trị: instance mặc định `suggest` (Phase 1 chỉ đọc/hỏi CLI, không cấp `full`).
- Marker cố định: `[APPOINT ...]`, `[ATTACH ...]`, `[DELEGATE inst:"..."; ...]`, `[SAY: ...]`, `[ASK: ...]`.
- Cap chống runaway: `MAX_ROUNDS=3`/lượt, timeout mỗi CLI 120s.
- Config = `config.json` (copy từ `config.example.json`), KHÔNG commit config thật.

---

### Task 1: Scaffold + config loader

**Files:**
- Create: `server/__init__.py`, `server/config.py`, `config.example.json`, `requirements.txt`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: str) -> Config`; `Config` có `.instances: list[Instance]`, `.settings: dict`. `Instance` = dataclass `{name:str, engine:str, agent_md:str|None, voice:str, role:str}`.

- [ ] **Step 1: Write failing test** — `tests/test_config.py`
```python
import json, tempfile, os
from server.config import load_config

def test_load_config_parses_instances():
    data = {"settings": {"max_rounds": 3},
            "instances": [{"name": "lead-1", "engine": "claude", "voice": "my-voice", "role": "Lead"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f); p = f.name
    cfg = load_config(p); os.unlink(p)
    assert cfg.settings["max_rounds"] == 3
    assert cfg.instances[0].name == "lead-1"
    assert cfg.instances[0].engine == "claude"
    assert cfg.instances[0].role == "Lead"
```

- [ ] **Step 2: Run → fail** — `python -m pytest tests/test_config.py -v` → FAIL (no module `server.config`).

- [ ] **Step 3: Implement** — `server/config.py`
```python
import json
from dataclasses import dataclass, field

@dataclass
class Instance:
    name: str
    engine: str            # claude | codex | gemini
    voice: str = "my-voice"
    role: str = "Assistant"
    agent_md: str | None = None

@dataclass
class Config:
    instances: list[Instance] = field(default_factory=list)
    settings: dict = field(default_factory=dict)

def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    inst = [Instance(**i) for i in raw.get("instances", [])]
    return Config(instances=inst, settings=raw.get("settings", {}))
```
Create `server/__init__.py`, `tests/__init__.py` (empty). `requirements.txt`: `fastapi`, `uvicorn[standard]`, `websockets`, `faster-whisper`, `pytest`.
`config.example.json`:
```json
{ "settings": { "max_rounds": 3, "cli_timeout": 120 },
  "instances": [
    { "name": "lead-1", "engine": "claude", "role": "Lead", "voice": "my-voice" },
    { "name": "coder-1", "engine": "codex", "role": "Coder", "voice": "profile-b" },
    { "name": "researcher-1", "engine": "gemini", "role": "Researcher", "voice": "profile-c" } ] }
```

- [ ] **Step 4: Run → pass** — `python -m pytest tests/test_config.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(config): loader + Instance/Config models"`

---

### Task 2: Blackboard (transcript + persist)

**Files:**
- Create: `server/blackboard.py`, `tests/test_blackboard.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Blackboard(session_path:str)` với `.add(speaker:str, role:str, content:str) -> None`, `.turns() -> list[dict]`, `.transcript_text() -> str`, auto-append jsonl. Mỗi turn `{speaker, role, content, ts_index}`.

- [ ] **Step 1: Write failing test**
```python
import tempfile, os, json
from server.blackboard import Blackboard

def test_blackboard_add_and_persist():
    d = tempfile.mkdtemp(); p = os.path.join(d, "s.jsonl")
    bb = Blackboard(p)
    bb.add("user", "User", "xin chào")
    bb.add("lead-1", "Lead", "chào bạn")
    assert len(bb.turns()) == 2
    assert "chào bạn" in bb.transcript_text()
    lines = open(p, encoding="utf-8").read().strip().splitlines()
    assert json.loads(lines[0])["speaker"] == "user"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `server/blackboard.py`
```python
import json, os

class Blackboard:
    def __init__(self, session_path: str):
        self.path = session_path
        os.makedirs(os.path.dirname(session_path), exist_ok=True)
        self._turns = []
        if os.path.exists(session_path):
            for line in open(session_path, encoding="utf-8"):
                line = line.strip()
                if line: self._turns.append(json.loads(line))

    def add(self, speaker: str, role: str, content: str) -> None:
        turn = {"speaker": speaker, "role": role, "content": content, "ts_index": len(self._turns)}
        self._turns.append(turn)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def turns(self): return list(self._turns)
    def transcript_text(self) -> str:
        return "\n".join(f"{t['speaker']} ({t['role']}): {t['content']}" for t in self._turns)
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `git commit -am "feat(blackboard): transcript model + jsonl persist"`

---

### Task 3: Agent adapter (spawn CLI)

**Files:**
- Create: `server/adapters.py`, `tests/test_adapters.py`

**Interfaces:**
- Consumes: `Instance` (Task 1).
- Produces: `build_command(inst: Instance, prompt: str) -> list[str]`; `run_agent(inst, prompt, timeout=120) -> str` (spawn + capture stdout; lỗi/timeout → `"[ERROR] <inst.name>: <lý do>"`). Claude dùng `claude -p --append-system-prompt <role>`; codex `codex exec`; gemini `gemini -p`.

- [ ] **Step 1: Write failing test** (test command-building — thuần, không spawn thật)
```python
from server.config import Instance
from server.adapters import build_command

def test_build_command_claude_includes_prompt_and_role():
    inst = Instance(name="lead-1", engine="claude", role="Lead")
    cmd = build_command(inst, "làm X")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert any("Lead" in c for c in cmd)   # role vào system prompt

def test_build_command_codex_and_gemini():
    assert build_command(Instance("c","codex",role="Coder"), "hi")[0] == "codex"
    assert build_command(Instance("g","gemini",role="Researcher"), "hi")[0] == "gemini"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `server/adapters.py`
```python
import subprocess
from server.config import Instance

def build_command(inst: Instance, prompt: str) -> list[str]:
    role_sys = f"Bạn đóng vai {inst.role} trong một nhóm agent do Lead điều phối. Trả lời ngắn gọn, đúng vai."
    if inst.engine == "claude":
        return ["claude", "-p", prompt, "--append-system-prompt", role_sys]
    if inst.engine == "codex":
        return ["codex", "exec", f"[{inst.role}] {prompt}"]
    if inst.engine == "gemini":
        return ["gemini", "-p", f"[{inst.role}] {prompt}"]
    raise ValueError(f"engine không hỗ trợ: {inst.engine}")

def run_agent(inst: Instance, prompt: str, timeout: int = 120) -> str:
    try:
        r = subprocess.run(build_command(inst, prompt), capture_output=True,
                           text=True, encoding="utf-8", timeout=timeout)
        out = (r.stdout or "").strip()
        return out if out else f"[ERROR] {inst.name}: rỗng (exit {r.returncode})"
    except subprocess.TimeoutExpired:
        return f"[ERROR] {inst.name}: timeout {timeout}s"
    except Exception as e:
        return f"[ERROR] {inst.name}: {e}"
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Smoke (thủ công, có mạng/auth):** `python -c "from server.adapters import run_agent; from server.config import Instance; print(run_agent(Instance('t','claude',role='Assistant'),'nói: pong', 60))"` → kỳ vọng có "pong".
- [ ] **Step 6: Commit** — `git commit -am "feat(adapters): build_command + run_agent 3 engine"`

---

### Task 4: Orchestrator (Lead loop + marker parsing)

**Files:**
- Create: `server/orchestrator.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Config`, `Blackboard`, `run_agent` (Task 3).
- Produces: `parse_markers(text:str) -> dict` (keys: `delegate: list[(inst,task)]`, `say: str|None`, `ask: str|None`); `run_turn(cfg, bb, user_text, agent_runner=run_agent) -> str` (trả `say`). `agent_runner` inject được để test.

- [ ] **Step 1: Write failing test**
```python
from server.orchestrator import parse_markers, run_turn
from server.config import Config, Instance
from server.blackboard import Blackboard
import tempfile, os

def test_parse_markers():
    t = '[DELEGATE researcher-1:"tìm X"; coder-1:"sửa Y"]\n[SAY: xong rồi]'
    m = parse_markers(t)
    assert ("researcher-1", "tìm X") in m["delegate"]
    assert ("coder-1", "sửa Y") in m["delegate"]
    assert m["say"] == "xong rồi"

def test_run_turn_delegates_then_says():
    cfg = Config(instances=[Instance("lead-1","claude",role="Lead"),
                            Instance("researcher-1","gemini",role="Researcher")],
                 settings={"max_rounds":3})
    calls = []
    def fake_runner(inst, prompt, timeout=120):
        calls.append(inst.name)
        if inst.role == "Lead" and "tìm" not in prompt:
            return '[DELEGATE researcher-1:"tìm X"]'
        if inst.role == "Lead":
            return '[SAY: đã có kết quả]'
        return "kết quả nghiên cứu X"
    bb = Blackboard(os.path.join(tempfile.mkdtemp(), "s.jsonl"))
    say = run_turn(cfg, bb, "nghiên cứu X giúp", agent_runner=fake_runner)
    assert say == "đã có kết quả"
    assert "researcher-1" in calls
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `server/orchestrator.py`
```python
import re
from server.config import Config

_DELEG = re.compile(r'([a-zA-Z0-9_\-#]+)\s*:\s*"([^"]*)"')

def parse_markers(text: str) -> dict:
    delegate = []
    for block in re.findall(r'\[DELEGATE([^\]]*)\]', text):
        delegate += [(n, t) for n, t in _DELEG.findall(block)]
    say = re.search(r'\[SAY:\s*(.*?)\]', text, re.S)
    ask = re.search(r'\[ASK:\s*(.*?)\]', text, re.S)
    return {"delegate": delegate, "say": say.group(1).strip() if say else None,
            "ask": ask.group(1).strip() if ask else None}

def _lead(cfg: Config):
    return next((i for i in cfg.instances if i.role == "Lead"), cfg.instances[0])

def _by_name(cfg: Config, name: str):
    return next((i for i in cfg.instances if i.name == name), None)

def run_turn(cfg, bb, user_text, agent_runner) -> str:
    from server.adapters import run_agent
    agent_runner = agent_runner or run_agent
    lead = _lead(cfg)
    bb.add("user", "User", user_text)
    max_rounds = cfg.settings.get("max_rounds", 3)
    prompt = (f"Transcript:\n{bb.transcript_text()}\n\n"
              "Bạn là Lead. Phân việc bằng marker [DELEGATE inst:\"...\"] nếu cần, "
              "rồi khi đủ thông tin trả lời cuối bằng [SAY: ...]. Instances: "
              + ", ".join(f"{i.name}({i.role})" for i in cfg.instances if i.role != "Lead"))
    for _ in range(max_rounds):
        out = agent_runner(lead, prompt)
        bb.add(lead.name, "Lead", out)
        m = parse_markers(out)
        if m["say"]:
            return m["say"]
        if m["ask"]:
            return m["ask"]
        results = []
        for name, task in m["delegate"]:
            inst = _by_name(cfg, name)
            if not inst:
                results.append(f"{name}: (không có instance)"); continue
            res = agent_runner(inst, task)
            bb.add(inst.name, inst.role, res)
            results.append(f"{inst.name}: {res}")
        prompt = (f"Transcript:\n{bb.transcript_text()}\n\n"
                  "Kết quả delegate ở trên. Nếu đủ, trả lời cuối bằng [SAY: ...].")
        if not m["delegate"]:
            return out  # Lead trả thẳng không marker
    return "Đã đạt giới hạn vòng, chưa có kết luận."
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `git commit -am "feat(orchestrator): marker parse + Lead loop"`

---

### Task 5: STT + TTS wrappers

**Files:**
- Create: `server/stt.py`, `server/tts.py`, `tests/test_voice.py`

**Interfaces:**
- Produces: `transcribe(audio_path:str) -> str` (faster-whisper); `synthesize(text:str, profile:str) -> str` (đường dẫn wav, gọi OmniVoice).

- [ ] **Step 1: Write test (mock-based — không tải model trong CI)**
```python
from unittest.mock import patch
from server import stt

def test_transcribe_calls_model(tmp_path):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFF....")
    with patch("server.stt._model") as m:
        m.transcribe.return_value = ([type("S",(),{"text":"xin chào"})()], None)
        assert stt.transcribe(str(wav)) == "xin chào"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `server/stt.py`
```python
from faster_whisper import WhisperModel
_model = WhisperModel("large-v3", device="auto", compute_type="auto")

def transcribe(audio_path: str) -> str:
    segments, _ = _model.transcribe(audio_path, language="vi")
    return "".join(s.text for s in segments).strip()
```
`server/tts.py` (gọi OmniVoice CLI/venv — theo `.tts/omnivoice`):
```python
import subprocess, os, tempfile
OV_PY = os.path.expanduser(r"~\.tts\omnivoice\.venv\Scripts\python.exe")
OV_SYNTH = os.path.expanduser(r"~\.tts\omnivoice\synth_cli.py")  # xác minh tên script thật ở Phase 1

def synthesize(text: str, profile: str = "my-voice") -> str:
    out = os.path.join(tempfile.gettempdir(), f"ac_{abs(hash(text))}.wav")
    subprocess.run([OV_PY, OV_SYNTH, "--text", text, "--profile", profile, "--out", out],
                   check=True, timeout=120)
    return out
```

- [ ] **Step 4: Run test → pass** (mock). **Smoke thủ công** TTS với 1 câu ngắn.
- [ ] **Step 5: Commit** — `git commit -am "feat(voice): stt (whisper) + tts (omnivoice) wrappers"`

> ⚠️ Xác minh ở Phase 1: tên script OmniVoice thật (`.tts/omnivoice`) + cách gọi profile (xem memory [[project_omnivoice_tts]]). Nếu OmniVoice có MCP, có thể gọi qua MCP thay subprocess.

---

### Task 6: FastAPI app + WebSocket

**Files:**
- Create: `server/app.py`, `web/index.html`, `web/app.js`, `web/style.css`

**Interfaces:**
- Consumes: tất cả trên. WS `/ws`: nhận `{type:"audio", data:<base64 wav>}` hoặc `{type:"text", data:str}` → chạy `run_turn` → gửi `{type:"turn", speaker, role, content}` cho mỗi turn + `{type:"say", audio_url}`.

- [ ] **Step 1: Implement `server/app.py`**
```python
import base64, json, tempfile, os
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from server.config import load_config
from server.blackboard import Blackboard
from server.orchestrator import run_turn
from server import stt, tts

app = FastAPI()
CFG = load_config(os.path.join(os.path.dirname(__file__), "..", "config.json"))
SESS = os.path.join(os.path.dirname(__file__), "..", "sessions", "current.jsonl")

@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    bb = Blackboard(SESS)
    while True:
        msg = json.loads(await sock.receive_text())
        if msg["type"] == "audio":
            wav = os.path.join(tempfile.gettempdir(), "in.wav")
            open(wav, "wb").write(base64.b64decode(msg["data"]))
            text = stt.transcribe(wav)
        else:
            text = msg["data"]
        await sock.send_text(json.dumps({"type":"turn","speaker":"user","role":"User","content":text}))
        say = run_turn(CFG, bb, text, agent_runner=None)
        for t in bb.turns()[-8:]:
            await sock.send_text(json.dumps({"type":"turn", **t}))
        audio = tts.synthesize(say, CFG.instances[0].voice)
        await sock.send_text(json.dumps({"type":"say","audio_url":f"/audio?p={audio}"}))

@app.get("/audio")
def audio(p: str): return FileResponse(p, media_type="audio/wav")

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__),"..","web"), html=True))
```

- [ ] **Step 2: Frontend `web/index.html` + `app.js`** — nút push-to-talk (MediaRecorder → base64 → WS), transcript render theo `speaker`/`role` (màu theo instance), phát `audio_url`. (Code JS đầy đủ ~80 dòng — mic capture, ws onmessage switch type turn/say, `new Audio(url).play()`.)

- [ ] **Step 3: Smoke** — `uvicorn server.app:app --port 7788` → mở `localhost:7788` → gõ text → thấy transcript + nghe audio.
- [ ] **Step 4: Commit** — `git commit -am "feat(app): FastAPI + WS + frontend push-to-talk"`

---

### Task 7: install.ps1 + run + docs

**Files:**
- Create: `install.ps1` (BOM), `run.ps1`, `README.md`

- [ ] **Step 1:** `install.ps1` — tạo venv, `pip install -r requirements.txt`, copy `config.example.json`→`config.json` nếu chưa có, in hướng dẫn `gemini` auth. UTF-8 **BOM** + parse-check.
- [ ] **Step 2:** `run.ps1` — `.venv\Scripts\uvicorn server.app:app --port 7788`, mở browser.
- [ ] **Step 3:** `README.md` — cài/chạy/cấu hình instances + voice + 3 mức tự trị.
- [ ] **Step 4: Commit** — `git commit -am "chore: install.ps1 + run.ps1 + README"`

---

## Self-Review
- **Spec coverage:** stt/tts/adapter/orchestrator/blackboard/web = Task 1-7 ✅. Agent Library UI + context manager + session rename/resume/remote = **Phase 2-4** (ngoài plan này, đúng phân pha). Marker APPOINT/ATTACH parse: Phase 1 xử lý DELEGATE/SAY/ASK; APPOINT/ATTACH để Phase 2 (khi có library) — ghi rõ.
- **Placeholder scan:** Task 6 Step 2 (JS) mô tả thay vì full code — engineer cần viết ~80 dòng JS chuẩn MediaRecorder+WS; chấp nhận ở mức plan (UI). TTS script name cần xác minh (đánh dấu ⚠️).
- **Type consistency:** `run_turn(cfg, bb, user_text, agent_runner)`, `parse_markers->dict{delegate,say,ask}`, `Instance{name,engine,voice,role,agent_md}`, `Blackboard.add/turns/transcript_text` — nhất quán across Task 1-6 ✅.

## Phạm vi Phase 1 chốt lại
MVP = nói/gõ → Lead(Claude) điều phối Codex/Gemini qua DELEGATE → tổng hợp → đọc (OmniVoice) + transcript. Chưa có: Agent Library UI, quét folder/upload, PageIndex routing, session rename/resume UI, remote toggle (Phase 2-4).
