import asyncio, base64, json, subprocess, tempfile, os
from fastapi import FastAPI, WebSocket, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from server.config import load_config
from server.blackboard import Blackboard
from server.orchestrator import run_turn
from server import stt, tts, voices
from server.agent_library import discover_agents, scan_folder_for_agents
from server.instances import InstanceStore
from server.context_manager import scan_folder, save_upload, route_context
from server.session import SessionManager

app = FastAPI()
CONFIG_PATH = os.environ.get(
    "AGENT_CONSOLE_CONFIG",
    os.path.join(os.path.dirname(__file__), "..", "config.json"),
)
CFG = load_config(CONFIG_PATH)
SESS = os.path.join(os.path.dirname(__file__), "..", "sessions", "current.jsonl")
UPLOAD_DIR = os.environ.get(
    "AGENT_CONSOLE_UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "..", "workspace", "uploads"),
)
SESSIONS_DIR = os.environ.get(
    "AGENT_CONSOLE_SESSIONS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "sessions"),
)
CURRENT_SESSION_ID: str | None = None
REMOTE_MANUAL_HINT = (
    "Nếu lệnh 'claude remote-control' không khả dụng trên máy này: dùng Claude "
    "Code app trên điện thoại (đăng nhập cùng tài khoản, mở phiên máy tính), "
    "hoặc trỏ ngrok/tailscale vào cổng 7788 của OpcOS Orbit thủ công."
)

AGENT_DIRS = ["~/.opcos/plugins", "~/.claude/agents"]


class CreateInstanceBody(BaseModel):
    agent_name: str
    engine: str | None = None
    voice: str = ""


class RenameInstanceBody(BaseModel):
    new_name: str


class UpdateInstanceBody(BaseModel):
    role: str | None = None
    engine: str | None = None
    model: str | None = None
    autonomy: str | None = None
    voice: str | None = None


class ScanPathBody(BaseModel):
    path: str


class AttachBody(BaseModel):
    instance: str
    path: str


class NewSessionBody(BaseModel):
    name: str


class RenameSessionBody(BaseModel):
    name: str


class RemoteToggleBody(BaseModel):
    on: bool


class VoiceDefaultBody(BaseModel):
    name: str


class VoiceCreateBody(BaseModel):
    instruct: str
    name: str


class InstanceVoiceBody(BaseModel):
    voice: str


@app.get("/api/agents")
def list_agents():
    return [a.__dict__ for a in discover_agents(AGENT_DIRS)]


@app.post("/api/agents/scan")
def scan_agents(body: ScanPathBody):
    return [a.__dict__ for a in scan_folder_for_agents(body.path)]


@app.get("/api/instances")
def list_instances():
    store = InstanceStore(CONFIG_PATH)
    return [i.__dict__ for i in store.list()]


@app.post("/api/instances")
def create_instance(body: CreateInstanceBody):
    store = InstanceStore(CONFIG_PATH)
    agents = {a.name: a for a in discover_agents(AGENT_DIRS)}
    agent = agents.get(body.agent_name)
    if agent is None:
        from server.agent_library import AgentDef
        agent = AgentDef(name=body.agent_name, engine=body.engine or "claude")
    inst = store.create(agent, body.engine, body.voice)
    return inst.__dict__


@app.patch("/api/instances/{name}")
def rename_instance(name: str, body: RenameInstanceBody):
    store = InstanceStore(CONFIG_PATH)
    if not any(i.name == name for i in store.list()):
        raise HTTPException(status_code=404, detail="instance not found")
    store.rename(name, body.new_name)
    return {"ok": True, "name": body.new_name}


@app.post("/api/instances/{name}/update")
def update_instance(name: str, body: UpdateInstanceBody):
    """Sửa role/engine/model/autonomy/voice từ UI (ép duy nhất 1 Lead)."""
    store = InstanceStore(CONFIG_PATH)
    updated = store.update(name, role=body.role, engine=body.engine,
                           model=body.model, autonomy=body.autonomy, voice=body.voice)
    if updated is None:
        raise HTTPException(status_code=404, detail="instance not found")
    return {"ok": True, "instance": updated}


@app.delete("/api/instances/{name}")
def delete_instance(name: str):
    store = InstanceStore(CONFIG_PATH)
    store.remove(name)
    return {"ok": True}

@app.post("/api/context/scan")
def scan_context(body: ScanPathBody):
    return scan_folder(body.path)


@app.post("/api/context/upload")
async def upload_context(file: UploadFile = File(...)):
    data = await file.read()
    dest = save_upload(file.filename, data, UPLOAD_DIR)
    return {"path": dest}


@app.post("/api/context/attach")
def attach_context(body: AttachBody):
    store = InstanceStore(CONFIG_PATH)
    if not any(i.name == body.instance for i in store.list()):
        raise HTTPException(status_code=404, detail="instance not found")
    result = route_context(body.path)
    return {"instance": body.instance, "path": body.path, **result}


@app.get("/api/sessions")
def list_sessions():
    return SessionManager(SESSIONS_DIR).list()


@app.post("/api/sessions")
def new_session(body: NewSessionBody):
    sm = SessionManager(SESSIONS_DIR)
    sid = sm.new(body.name)
    return {"id": sid, "name": body.name}


@app.post("/api/sessions/{sid}/stop")
def stop_session(sid: str):
    """TẮT phiên: kill mọi task agent đang chạy nền + archive (giữ lịch sử, resume được)."""
    from server import adapters
    killed = adapters.stop_all_jobs()
    sm = SessionManager(SESSIONS_DIR)
    sm.set_archived(sid, True)
    return {"ok": True, "killed_jobs": killed, "archived": sid}


@app.post("/api/sessions/{sid}/unarchive")
def unarchive_session(sid: str):
    """RESUME phiên đã archive: bỏ cờ archived → hiện lại trên tab, mở tiếp được."""
    sm = SessionManager(SESSIONS_DIR)
    sm.set_archived(sid, False)
    return {"ok": True, "resumed": sid}


@app.patch("/api/sessions/{sid}")
def rename_session(sid: str, body: RenameSessionBody):
    sm = SessionManager(SESSIONS_DIR)
    if sid not in sm.data:
        raise HTTPException(status_code=404, detail="session not found")
    sm.rename(sid, body.name)
    return {"ok": True, "id": sid, "name": body.name}


@app.post("/api/sessions/{sid}/resume")
def resume_session(sid: str):
    global CURRENT_SESSION_ID
    sm = SessionManager(SESSIONS_DIR)
    if sid not in sm.data:
        raise HTTPException(status_code=404, detail="session not found")
    bb = sm.load(sid)
    CURRENT_SESSION_ID = sid
    return {"id": sid, "name": sm.data[sid].get("name", ""), "turns": bb.turns()}


@app.post("/api/remote/toggle")
def remote_toggle(body: RemoteToggleBody):
    action = "on" if body.on else "off"
    try:
        from server.adapters import _resolve
        result = subprocess.run(
            _resolve("claude") + ["remote-control", action],
            capture_output=True, text=True, timeout=15,
        )
        ok = result.returncode == 0
        output = (result.stdout or result.stderr or "").strip()
    except Exception as exc:  # binary/subcommand missing, timeout, etc.
        ok = False
        output = str(exc)
    return {"requested": action, "ok": ok, "output": output, "manual_hint": REMOTE_MANUAL_HINT}


# ===== Console v2 "Mission Control": Agents dashboard + System pane =====

if os.environ.get("AGENT_CONSOLE_DEMO_JOBS") == "1":
    # Seed job giả cho dogfood UI (KHÔNG bật ở chạy thật) — đủ 4 trạng thái.
    from server import jobs as _dj
    import time as _t
    _j1 = _dj.create("lead-1", "claude", "Tổng hợp phân tích repo herdr và odysseus")
    _j1._last_output_at = _t.time(); _j1.feed_line("Đang đọc blueprint UI...")
    _j2 = _dj.create("coder-1", "codex", "Viết unit test cho jobs.py")
    _j2.feed_line("Do you want to proceed? (y/N)  › 1. Yes  2. No")
    _j2._last_output_at = _t.time() - 30
    _j3 = _dj.create("researcher-1", "agy", "Tra cứu pattern multiplexer")
    _j3.feed_line("KẾT QUẢ: đã tổng hợp 5 pattern chính"); _j3.finish(0)
    _j4 = _dj.create("draft-1", "ollama", "Dịch tóm tắt sang tiếng Việt")
    _j4.feed_line("connection refused"); _j4.finish(1, "ollama không chạy")

@app.get("/api/jobs")
def api_jobs():
    from server import jobs
    return {"jobs": jobs.list_jobs(), "summary": jobs.summary()}


@app.post("/api/jobs/{job_id}/kill")
def api_kill_job(job_id: int):
    from server import jobs
    from server.adapters import _kill_tree
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="job not found")
    if j.pid and j.ended_at is None:
        _kill_tree(j.pid)
        j.finish(None, "killed by user")
    return {"ok": True, "id": job_id}


@app.post("/api/jobs/{job_id}/seen")
def api_seen_job(job_id: int):
    from server import jobs
    if not jobs.mark_seen(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True}


@app.post("/api/jobs/seen-all")
def api_seen_all():
    from server import jobs
    return {"ok": True, "marked": jobs.mark_all_seen()}


@app.get("/api/system")
def api_system():
    from server import system_info
    return {"registry": system_info.registry_summary(),
            "mcp": system_info.mcp_servers()}


@app.get("/api/system/registry-page")
def api_registry_page():
    from fastapi.responses import HTMLResponse
    from server import system_info
    html = system_info.registry_html()
    if html is None:
        raise HTTPException(status_code=404, detail="registry.html không có — chạy build-registry.ps1")
    return HTMLResponse(html)


@app.get("/api/system/mcp-live")
def api_mcp_live():
    """Kiểm tra LIVE MCP (chạy `claude mcp list`, chậm 10-60s) — trạng thái thật."""
    from server import system_info
    return system_info.mcp_live()


@app.get("/api/voices")
def get_voices():
    return voices.list_voices()


@app.post("/api/voices/default")
def set_default_voice(body: VoiceDefaultBody):
    voices.set_default(body.name)
    return {"ok": True, "name": body.name}


@app.post("/api/voices/clone")
async def clone_voice(
    file: UploadFile = File(...),
    ref_text: str = Form(...),
    name: str = Form(...),
):
    data = await file.read()
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    fd, wav_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = voices.clone_from_wav(wav_path, ref_text, name)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
    return {"ok": True, "name": name, "result": result}


@app.post("/api/voices/create")
def create_voice(body: VoiceCreateBody):
    result = voices.create_from_instruct(body.instruct, body.name)
    return {"ok": True, "name": body.name, "result": result}


@app.delete("/api/voices/{name}")
def remove_voice(name: str):
    voices.delete_voice(name)
    return {"ok": True, "name": name}


@app.post("/api/instances/{name}/voice")
def set_instance_voice(name: str, body: InstanceVoiceBody):
    store = InstanceStore(CONFIG_PATH)
    found = False
    for i in store.raw["instances"]:
        if i["name"] == name:
            i["voice"] = body.voice
            found = True
    if not found:
        raise HTTPException(status_code=404, detail="instance not found")
    store._save()
    return {"ok": True, "name": name, "voice": body.voice}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    sm = SessionManager(SESSIONS_DIR)
    bb = Blackboard(SESS)          # phiên nháp mặc định khi chưa mở phiên nào
    active_id = None
    voice_on = False               # MẶC ĐỊNH TẮT giọng → không chạy OmniVoice (tiết kiệm tài nguyên)
    while True:
        msg = json.loads(await sock.receive_text())
        mt = msg.get("type")
        if mt == "open":           # MỞ 1 phiên → nạp + gửi TOÀN BỘ lịch sử để render dạng chat
            active_id = msg["id"]
            bb = sm.load(active_id)
            await sock.send_text(json.dumps(
                {"type": "history", "id": active_id, "turns": bb.turns()}, ensure_ascii=False))
            continue
        if mt == "close":          # ĐÓNG phiên → về nháp, xoá khung chat
            active_id = None
            bb = Blackboard(SESS)
            await sock.send_text(json.dumps({"type": "cleared"}))
            continue
        if mt == "voice":          # bật/tắt trả lời bằng giọng (chỉ khi bật mới kích hoạt OmniVoice)
            voice_on = bool(msg.get("on"))
            continue
        if mt == "audio":
            wav = os.path.join(tempfile.gettempdir(), "in.wav")
            open(wav, "wb").write(base64.b64decode(msg["data"]))
            text = stt.transcribe(wav)
            if not text.strip():
                await sock.send_text(json.dumps({"type": "pending_off"}))
                continue
        else:
            text = msg["data"]
        # báo "đang xử lý" NGAY (CLI cold-start có thể 10-60s — để user không tưởng treo)
        await sock.send_text(json.dumps({"type": "pending"}))
        before = len(bb.turns())
        say = await asyncio.to_thread(run_turn, CFG, bb, text, None)
        # CHỈ gửi turn MỚI của lượt này, BỎ turn user (client đã tự hiện) → hết duplicate
        for turn in bb.turns()[before:]:
            if turn.get("speaker") == "user":
                continue
            await sock.send_text(json.dumps({"type": "turn", **turn}, ensure_ascii=False))
        await sock.send_text(json.dumps({"type": "pending_off"}))
        if voice_on:               # CHỈ chạy OmniVoice khi user bật nghe → tiết kiệm tài nguyên
            audio = await asyncio.to_thread(tts.synthesize, say, CFG.instances[0].voice)
            await sock.send_text(json.dumps({"type": "say", "audio_url": f"/audio?p={audio}"}))

@app.get("/audio")
def audio(p: str): return FileResponse(p, media_type="audio/wav")

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__),"..","web"), html=True))
