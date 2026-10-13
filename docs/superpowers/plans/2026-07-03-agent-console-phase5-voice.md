# Agent Console — Phase 5 (Voice Studio + OmniVoice install) Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Steps `- [ ]`.

**Goal:** Voice Studio trong console (clone/tạo/quản lý/gán giọng) + OmniVoice là dependency BẮT BUỘC (install tự lo) + bundle giọng my-voice làm default (máy khác cũng có).

**Architecture:** Nối tiếp (branch `phase5-voice`). Thêm `server/voices.py` (bọc API OmniVoice qua subprocess venv omnivoice, giống `server/tts.py`), endpoints `/api/voices/*`, panel `web/voices.js`. Bundle `assets/voices/my-voice.{wav,txt}` + restore khi install. OmniVoice installer mới.

**Tech Stack:** như trước. OmniVoice API: `voice_profiles.py` (`list_profiles/set_default/save_profile_from_wav/save_profile_from_instruct`) tại `~/.tts/omnivoice`; venv `~/.tts/omnivoice/.venv/Scripts/python.exe`.

## Global Constraints
- Repo `~/.mcp/agent-console` branch `phase5-voice`. venv `.venv/Scripts/python.exe`. `.ps1` UTF-8 BOM.
- OmniVoice = **bắt buộc** (không degrade). Gọi qua subprocess venv omnivoice, `cwd=~/.tts/omnivoice`, `import voice_profiles`/`import mcp_server` (pattern có sẵn trong `server/tts.py`).
- Bundle: `assets/voices/my-voice.{wav,txt}` + `_default.txt` đã có trong repo. Không nạp PROTECTED.
- In chữ Việt phải UTF-8 (cp1252 vỡ ở console).

---

### Task 1: server/voices.py — bọc API voice OmniVoice
**Files:** Create `server/voices.py`, `tests/test_voices.py`
**Interfaces:** Produces `_ov_call(func_snippet, *args)->str` (spawn venv omnivoice, cwd, chạy snippet); `list_voices()->list[str]`; `set_default(name)->str`; `clone_from_wav(wav_path, ref_text, name)->str`; `create_from_instruct(instruct, name)->str`; `delete_voice(name)->str`. Test = kiểm command-building (mock subprocess), KHÔNG chạy model thật.

- [ ] **Step 1: test** `tests/test_voices.py`
```python
from unittest.mock import patch
from server import voices

def test_list_voices_parses(tmp_path):
    with patch("server.voices._ov_call") as m:
        m.return_value = '["my-voice","giong-b"]'
        assert voices.list_voices() == ["my-voice", "giong-b"]

def test_clone_builds_call():
    with patch("server.voices.subprocess.run") as m:
        m.return_value.stdout = "OK"; m.return_value.returncode = 0
        voices.clone_from_wav("C:/a.wav", "xin chào", "test")
        args = m.call_args[0][0]
        assert any("save_profile_from_wav" in str(a) for a in args)
        assert "test" in args
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** `server/voices.py`
```python
import os, subprocess, json
OV_DIR = os.path.expanduser(r"~\.tts\omnivoice")
OV_PY = os.path.join(OV_DIR, ".venv", "Scripts", "python.exe")

def _ov_call(snippet: str, *args) -> str:
    r = subprocess.run([OV_PY, "-c", snippet, *[str(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=OV_DIR, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "OmniVoice call failed")[-400:])
    return (r.stdout or "").strip()

def list_voices() -> list:
    out = _ov_call("import voice_profiles as vp, json, sys; sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(vp.list_profiles(), ensure_ascii=False))")
    try: return json.loads(out.splitlines()[-1])
    except Exception: return []

def set_default(name: str) -> str:
    return _ov_call("import voice_profiles as vp, sys; vp.set_default(sys.argv[1]); print('ok')", name)

def clone_from_wav(wav_path: str, ref_text: str, name: str) -> str:
    return _ov_call(
        "import voice_profiles as vp, sys; sys.stdout.reconfigure(encoding='utf-8');"
        "print(vp.save_profile_from_wav(sys.argv[1], sys.argv[2], sys.argv[3], set_as_default=False))",
        wav_path, ref_text, name)

def create_from_instruct(instruct: str, name: str) -> str:
    # model=None → save_profile_from_instruct tự load model mặc định trong hàm
    return _ov_call(
        "import voice_profiles as vp, mcp_server as ov, sys; sys.stdout.reconfigure(encoding='utf-8');"
        "m=ov._load_model() if hasattr(ov,'_load_model') else None;"
        "print(vp.save_profile_from_instruct(m, sys.argv[1], sys.argv[2], set_as_default=False))",
        instruct, name)

def delete_voice(name: str) -> str:
    voices_dir = os.path.join(OV_DIR, "voices")
    for ext in (".wav", ".txt"):
        p = os.path.join(voices_dir, name + ext)
        if os.path.exists(p): os.remove(p)
    return "deleted"
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: Smoke thủ công** (có model): `list_voices()` trả `["my-voice",...]`.
- [ ] **Step 6: commit** `git add -A && git commit -m "feat(voices): bọc API voice OmniVoice (list/clone/create/default/delete)"`

---

### Task 2: Voice API endpoints + panel + gán giọng
**Files:** Modify `server/app.py`; Create `web/voices.js`; Modify `web/index.html`
**Interfaces:** REST `GET /api/voices`, `POST /api/voices/default {name}`, `POST /api/voices/clone` (multipart wav + ref_text + name), `POST /api/voices/create {instruct,name}`, `DELETE /api/voices/{name}`, `POST /api/instances/{name}/voice {voice}` (gán giọng cho instance qua InstanceStore).
- [ ] **Step 1: test** `tests/test_voices_api.py` (TestClient, mock server.voices): GET /api/voices trả list; POST /api/voices/default 200; POST /api/instances/{n}/voice cập nhật InstanceStore. Assert 200 + JSON.
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** endpoints (import server.voices + InstanceStore). Frontend `web/voices.js`: panel "🎙️ Voice Studio" — list giọng, nút Set-default, form Clone (chọn wav + ref text), form Create (instruct), dropdown gán giọng cho từng instance, nút xoá. (~70 dòng JS.)
- [ ] **Step 4: run pytest→pass; commit** `git commit -am "feat(app): Voice Studio API + panel + gán giọng instance"`

---

### Task 3: Restore bundle + wire agent-console install (bắt buộc OmniVoice)
**Files:** Create `server/voice_setup.py`, `tests/test_voice_setup.py`; Modify `install.ps1`, `README.md`
**Interfaces:** Produces `restore_bundled_voices(assets_dir, omni_voices_dir)->list[str]` (copy `*.wav/*.txt` + `_default.txt` từ assets → omnivoice/voices, skip nếu đã có), `set_bundled_default()`.
- [ ] **Step 1: test**
```python
from server.voice_setup import restore_bundled_voices
def test_restore_copies(tmp_path):
    a = tmp_path/"assets"; a.mkdir(); (a/"my-voice.wav").write_bytes(b"RIFF"); (a/"my-voice.txt").write_text("x"); (a/"_default.txt").write_text("my-voice")
    dst = tmp_path/"voices"; dst.mkdir()
    got = restore_bundled_voices(str(a), str(dst))
    assert "my-voice" in got and (dst/"my-voice.wav").exists() and (dst/"_default.txt").read_text()=="my-voice"
```
- [ ] **Step 2: run→fail.**
- [ ] **Step 3: implement** `server/voice_setup.py`
```python
import os, shutil
def restore_bundled_voices(assets_dir: str, omni_voices_dir: str) -> list:
    os.makedirs(omni_voices_dir, exist_ok=True); restored = []
    for f in os.listdir(assets_dir):
        if f.endswith((".wav", ".txt")):
            dst = os.path.join(omni_voices_dir, f)
            if not os.path.exists(dst): shutil.copy2(os.path.join(assets_dir, f), dst)
            if f.endswith(".wav"): restored.append(f[:-4])
    return restored
```
- [ ] **Step 4: run→pass.**
- [ ] **Step 5: wire `install.ps1`** — thêm bước: kiểm `~/.tts/omnivoice/.venv`; THIẾU → chạy `~/.tts/omnivoice/install.ps1` (Task 4); rồi `restore_bundled_voices(assets/voices, ~/.tts/omnivoice/voices)` (gọi qua venv) + set default my-voice. Cập nhật README (yêu cầu OmniVoice, giọng default my-voice). BOM.
- [ ] **Step 6: commit** `git commit -am "feat(install): restore bundle my-voice + require OmniVoice"`

---

### Task 4: OmniVoice installer (best-effort)
**Files:** Create `C:/Users/DucNguyen/.tts/omnivoice/install.ps1` (BOM)
- [ ] **Step 1:** viết `install.ps1`: tạo `.venv` (python -m venv), cài `torch` (ghi chú index-url cu126 cho GPU; CPU fallback), cài `omnivoice` + deps từ `requirements.txt` nếu có (nếu không, in danh sách package cần + hướng dẫn), in hướng dẫn tải model lần đầu. Best-effort: chỗ nào máy-riêng (CUDA/model) → in cảnh báo rõ, KHÔNG fail cứng. BOM + parse-check.
- [ ] **Step 2: smoke** parse-check bằng `[scriptblock]::Create`. (KHÔNG chạy full install trong CI.)
- [ ] **Step 3: commit** (trong repo agent-console: chỉ commit nếu file nằm trong repo — nếu ngoài repo thì ghi chú đường dẫn trong README, KHÔNG commit file ngoài repo). → Đặt bản nguồn ở `agent-console/assets/omnivoice-install.ps1` + install.ps1 copy sang `~/.tts/omnivoice/` khi thiếu.
- [ ] **Step 4: commit** `git commit -am "feat(install): OmniVoice best-effort installer (assets/omnivoice-install.ps1)"`

---

## Self-Review
- **Coverage:** Voice Studio (clone/create/list/default/assign/delete)=T1-2 ✅; bundle+require OmniVoice=T3 ✅; OmniVoice installer=T4 ✅.
- **Placeholder:** UI panel (T2) mô tả JS — chấp nhận; logic có test. T4 installer là script best-effort (GPU/model máy-riêng) — smoke parse-check.
- **Type consistency:** `voices.{list_voices,set_default,clone_from_wav,create_from_instruct,delete_voice}`, `restore_bundled_voices(assets,dst)`, endpoints khớp `web/voices.js` — nhất quán.
- **Lưu ý privacy:** bundle my-voice.wav (giọng cá nhân) đi theo repo sang máy khác — user đã quyết. Ghi trong README.
